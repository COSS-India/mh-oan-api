"""
Pest & disease detection: Mahapocra/TIH API calls via agent tools.

Upload (temp file + Redis) lives in app.routers.upload.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from langfuse import observe
from pydantic_ai import ModelRetry

from app.config import settings
from app.routers.upload import get_pest_upload, update_pest_upload
from helpers.utils import get_logger

logger = get_logger(__name__)


def _read_image_bytes(image_path: str) -> bytes:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Uploaded image file not found at {image_path}.")
    return path.read_bytes()


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _extract_pd_id(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("pd_id", "pdId", "id"):
        value = payload.get(key)
        if value:
            return str(value)

    for nested_key in ("data", "result", "response"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            pd_id = _extract_pd_id(nested)
            if pd_id:
                return pd_id
    return None


def _extract_predictions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("predictions", "prediction", "results", "diseases"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, dict):
        nested = _extract_predictions(data)
        if nested:
            return nested

    if any(
        key in payload
        for key in ("disease_type", "disease", "disease_name", "label", "name")
    ):
        return [payload]
    return []


def _resolve_predict_pd_id(
    predict_response: Dict[str, Any],
    predictions: List[Dict[str, Any]],
) -> Optional[str]:
    pd_id = _extract_pd_id(predict_response)
    if pd_id:
        return pd_id

    for prediction in predictions:
        for key in ("pd_id", "disease_id", "id"):
            value = prediction.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _extract_advisory_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _format_advisory_for_farmer(
    advisory_response: Dict[str, Any],
    predictions: List[Dict[str, Any]],
) -> str:
    """
    Format Mahapocra crop_pd_advisory response for chat:
    Always show explicit headers (Crop / Disease-Pest), then advisory blocks.
    """
    items = _extract_advisory_items(advisory_response)
    item = items[0] if items else {}

    crop_name = (
        advisory_response.get("crop_name_mr")
        or item.get("crop_name_mr")
        or item.get("crop_name")
        or ""
    ).strip()
    disease = (item.get("disease_pest_mr") or item.get("disease_pest") or "").strip()
    preventive = (item.get("preventive_measures") or "").strip()
    curative = (item.get("curative_measures") or "").strip()

    if not disease and predictions:
        top = predictions[0]
        disease = (
            top.get("disease_type")
            or top.get("disease_name")
            or top.get("disease")
            or ""
        ).strip()

    header_lines: List[str] = []
    if crop_name:
        header_lines.append(f"**Crop name:** {crop_name}")
    if disease:
        header_lines.append(f"**Pest/Disease name:** {disease}")

    advisory_sections: List[str] = []
    if preventive:
        advisory_sections.append(
            "**Preventive measures (bachav ke upay):**\n" + preventive
        )
    if curative:
        advisory_sections.append(
            "**Curative measures (ilaaj ke upay):**\n" + curative
        )

    parts: List[str] = []
    if header_lines:
        parts.append("\n".join(header_lines))
    if advisory_sections:
        parts.append("\n\n".join(advisory_sections))

    if parts:
        return "\n\n".join(parts)

    for key in ("advisory", "advisory_text", "message", "text", "content"):
        value = advisory_response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(advisory_response, ensure_ascii=False)


def _format_prediction_summary(predictions: List[Dict[str, Any]]) -> str:
    if not predictions:
        return "No disease prediction was returned by the analysis service."

    lines = []
    for index, prediction in enumerate(predictions[:3], start=1):
        name = (
            prediction.get("disease_type")
            or prediction.get("disease_name")
            or prediction.get("disease")
            or prediction.get("label")
            or prediction.get("name")
            or prediction.get("class_name")
            or "Unknown disease"
        )
        confidence = (
            prediction.get("confidence_score")
            or prediction.get("confidence")
            or prediction.get("score")
            or prediction.get("probability")
        )
        if confidence is not None:
            lines.append(f"{index}. {name} (confidence: {confidence})")
        else:
            lines.append(f"{index}. {name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mahapocra / TIH HTTP
# ---------------------------------------------------------------------------


async def _post_multipart_predict(
    url: str,
    upload_record: Dict[str, Any],
    image_bytes: bytes,
) -> Dict[str, Any]:
    data = {
        "crop_id": upload_record["crop_id"],
        "crop_type": upload_record["crop_type"],
        "sowing_date": upload_record["sowing_date"],
    }
    files = {
        "image": (
            upload_record.get("image_filename") or f"{upload_record['upload_id']}.jpg",
            image_bytes,
            upload_record.get("content_type") or "image/jpeg",
        )
    }

    timeout = settings.pest_detection_http_timeout
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, data=data, files=files)
        response.raise_for_status()
        if response.content:
            return response.json()
        return {}


async def _post_crop_pd_advisory(url: str, pd_id: str) -> Dict[str, Any]:
    timeout = settings.pest_detection_http_timeout
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, data={"pd_id": pd_id})
        response.raise_for_status()
        if response.content:
            return response.json()
        return {}


async def _post_store_response(
    url: str,
    upload_record: Dict[str, Any],
    image_bytes: bytes,
    predict_response: Dict[str, Any],
    pd_id: str,
) -> Dict[str, Any]:
    data = {
        "crop_id": str(upload_record["crop_id"]),
        "sowing_date": upload_record["sowing_date"],
        "is_success": "true",
        "response": json.dumps(predict_response, ensure_ascii=False),
        "user_id": "",
        "pd_id": pd_id,
    }
    files = {
        "image": (
            upload_record.get("image_filename") or f"{upload_record['upload_id']}.jpg",
            image_bytes,
            upload_record.get("content_type") or "image/jpeg",
        )
    }

    timeout = settings.pest_detection_http_timeout
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, data=data, files=files)
        response.raise_for_status()
        if response.content:
            return response.json()
        return {}

async def run_pest_detection_analysis(upload_id: str) -> str:
    upload_record = await get_pest_upload(upload_id)
    if not upload_record:
        return (
            f"No uploaded image was found for upload_id '{upload_id}'. "
            "Ask the farmer to upload the crop photo again from the app."
        )

    image_bytes = _read_image_bytes(upload_record["image_path"])

    predict_url = os.getenv(
        "PEST_DETECTION_PREDICT_URL"
    )
    advisory_url = os.getenv(
        "PEST_DETECTION_ADVISORY_URL"
    )
    store_response_url = os.getenv(
        "PEST_DETECTION_STORE_RESPONSE_URL"
    )

    try:
        predict_response = await _post_multipart_predict(
            predict_url,
            upload_record,
            image_bytes,
        )
    except httpx.HTTPError as exc:
        logger.exception("Pest detection predict API failed for %s", upload_id)
        return f"Pest detection prediction failed: {exc}"

    predictions = _extract_predictions(predict_response)
    predict_pd_id = _resolve_predict_pd_id(predict_response, predictions)
    if not predict_pd_id:
        logger.error(
            "Predict response missing pd_id for %s: %s", upload_id, predict_response
        )
        return (
            "The pest detection service did not return a valid prediction reference. "
            "Please try uploading the image again."
        )

    try:
        advisory_response = await _post_crop_pd_advisory(
            advisory_url,
            predict_pd_id,
        )
    except httpx.HTTPError as exc:
        logger.exception("Pest detection advisory API failed for %s", upload_id)
        return (
            f"Disease prediction completed, but advisory lookup failed: {exc}\n\n"
            f"Prediction summary:\n{_format_prediction_summary(predictions)}"
        )

    farmer_message = _format_advisory_for_farmer(advisory_response, predictions)

    store_pd_id = _extract_pd_id(advisory_response) or predict_pd_id

    try:
        await _post_store_response(
            store_response_url,
            upload_record,
            image_bytes,
            predict_response,
            store_pd_id,
        )
    except httpx.HTTPError as exc:
        logger.exception("Pest detection store-response API failed for %s", upload_id)
        return (
            f"{farmer_message}\n\n"
            "(Note: analysis completed but storing the result on the server failed.)\n\n"
            "Please try again later."
        )

    analysis = {
        "predict_pd_id": predict_pd_id,
        "store_pd_id": store_pd_id,
        "predict_response": predict_response,
        "predictions": predictions,
        "advisory_response": advisory_response,
        "farmer_message": farmer_message,
    }
    await update_pest_upload(upload_record["upload_id"], {"analysis": analysis})

    return farmer_message


# ---------------------------------------------------------------------------
# Agent tools
# ---------------------------------------------------------------------------


@observe(name="tool:analyze_pest_disease_image", as_type="tool")
async def analyze_pest_disease_image(upload_id: str) -> str:
    """
    Run pest and disease analysis for a crop image that was uploaded earlier.

    Call this immediately when the farmer asks for pest/disease analysis and the
    message contains an upload id (e.g. pest_5a466793-ca9d-4104-80a5-434344a19f7a
    or a bare UUID from POST /api/upload). Do not use search_terms or
    search_documents for photo-based pest analysis.

    Loads crop metadata and image from Redis, calls the predict API, then fetches
    advisory text for the predicted disease id (pd_id).

    Args:
        upload_id: Full upload id from the upload API (with or without pest_ prefix).

    Returns:
        Formatted text: bold crop name, bold disease/pest, then preventive and curative
        sections with Hinglish titles. Relay to the farmer with the same formatting.
    """
    upload_id = upload_id.strip().rstrip("-.,;:")
    if not upload_id:
        raise ModelRetry("upload_id is required to analyze a pest detection image.")

    try:
        return await run_pest_detection_analysis(upload_id)
    except FileNotFoundError:
        logger.exception("Uploaded pest image file missing for %s", upload_id)
        return (
            f"The uploaded image file is no longer available for upload_id '{upload_id}'. "
            "Ask the farmer to upload the photo again from the app."
        )
    except Exception as exc:
        logger.exception("Unexpected pest detection analysis failure for %s", upload_id)
        raise ModelRetry(f"Pest detection analysis failed: {exc}") from exc
