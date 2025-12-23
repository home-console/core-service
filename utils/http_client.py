"""
HTTP client utilities for communicating with client-manager service.
Async implementation using httpx.
"""
import os
import json
import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException
import httpx

logger = logging.getLogger(__name__)

# Глобальный async HTTP клиент (создается при первом использовании)
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    """Получить или создать глобальный async HTTP клиент."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            verify=False,  # Dev mode: disable SSL verification
            follow_redirects=True
        )
    return _http_client


async def _close_http_client():
    """Закрыть глобальный HTTP клиент (для cleanup)."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def _http_json(
    method: str,
    url: str,
    body: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
    timeout: float = 15.0
) -> Any:
    """
    Make an async JSON HTTP request to client-manager service.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        url: URL path (e.g., "/api/clients")
        body: Optional JSON body
        headers: Optional HTTP headers
        timeout: Request timeout in seconds
        
    Returns:
        Parsed JSON response
        
    Raises:
        HTTPException: On HTTP errors or connection failures
    """
    base = os.getenv("CM_BASE_URL", "http://127.0.0.1:10000")
    base_url = base.rstrip('/')
    if not url.startswith("/"):
        url = "/" + url
    full_url = f"{base_url}{url}"
    
    client = _get_http_client()
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    
    try:
        response = await client.request(
            method=method.upper(),
            url=full_url,
            json=body,
            headers=request_headers,
            timeout=timeout
        )
        response.raise_for_status()
        
        # Пытаемся распарсить JSON, если не получается - возвращаем текст
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            text = response.text
            return json.loads(text) if text else None
            
    except httpx.HTTPStatusError as e:
        error_text = e.response.text if e.response else "Upstream error"
        logger.error(f"HTTP error {e.response.status_code if e.response else 'unknown'}: {error_text}")
        raise HTTPException(
            status_code=e.response.status_code if e.response else 500,
            detail=error_text
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        logger.error(f"Connection error to client-manager: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Client manager unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in HTTP request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


async def _http_multipart(
    path: str,
    fields: Dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    file_content_type: str = "application/octet-stream",
    timeout: float = 30.0
) -> Any:
    """
    Send an async multipart/form-data POST to client-manager.
    
    Args:
        path: URL path
        fields: Form fields (key-value pairs)
        file_field: Name of the file field
        filename: Name of the file
        file_bytes: File content as bytes
        file_content_type: MIME type of the file
        timeout: Request timeout
        
    Returns:
        Parsed JSON response
        
    Raises:
        HTTPException: On HTTP errors or connection failures
    """
    base = os.getenv("CM_BASE_URL", "http://127.0.0.1:10000")
    base_url = base.rstrip('/')
    if not path.startswith("/"):
        path = "/" + path
    full_url = f"{base_url}{path}"
    
    client = _get_http_client()
    
    # Подготавливаем файл для multipart
    files = {
        file_field: (filename, file_bytes, file_content_type)
    }
    
    try:
        response = await client.post(
            full_url,
            data=fields,
            files=files,
            timeout=timeout
        )
        response.raise_for_status()
        
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            text = response.text
            return json.loads(text) if text else None
            
    except httpx.HTTPStatusError as e:
        error_text = e.response.text if e.response else "Upstream error"
        logger.error(f"HTTP error in multipart upload: {error_text}")
        raise HTTPException(
            status_code=e.response.status_code if e.response else 500,
            detail=error_text
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        logger.error(f"Connection error in multipart upload: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Client manager unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in multipart upload: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


async def _http_multipart_stream(
    path: str,
    fields: Dict[str, str],
    file_field: str,
    filename: str,
    file_path: str,
    file_content_type: str = "application/octet-stream",
    timeout: float = 30.0
) -> Any:
    """
    Stream an async multipart/form-data POST to client-manager.
    Uses file streaming to avoid loading the whole file into memory.
    
    Args:
        path: URL path
        fields: Form fields
        file_field: Name of the file field
        filename: Name of the file
        file_path: Path to the file on disk
        file_content_type: MIME type
        timeout: Request timeout
        
    Returns:
        Parsed JSON response
        
    Raises:
        HTTPException: On HTTP errors or connection failures
    """
    base = os.getenv("CM_BASE_URL", "http://127.0.0.1:10000")
    base_url = base.rstrip('/')
    if not path.startswith("/"):
        path = "/" + path
    full_url = f"{base_url}{path}"
    
    client = _get_http_client()
    
    # Используем aiofiles для async чтения файла, если доступно
    # Иначе читаем файл синхронно (для небольших файлов это нормально)
    try:
        import aiofiles
        use_async = True
    except ImportError:
        use_async = False
    
    if use_async:
        # Async чтение файла
        async def file_stream():
            async with aiofiles.open(file_path, "rb") as f:
                while True:
                    chunk = await f.read(64 * 1024)  # 64KB chunks
                    if not chunk:
                        break
                    yield chunk
        
        files = {
            file_field: (filename, file_stream(), file_content_type)
        }
    else:
        # Синхронное чтение (для совместимости)
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        files = {
            file_field: (filename, file_data, file_content_type)
        }
    
    try:
        response = await client.post(
            full_url,
            data=fields,
            files=files,
            timeout=timeout
        )
        response.raise_for_status()
        
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            text = response.text
            return json.loads(text) if text else None
            
    except httpx.HTTPStatusError as e:
        error_text = e.response.text if e.response else "Upstream error"
        logger.error(f"HTTP error in streaming upload: {error_text}")
        raise HTTPException(
            status_code=e.response.status_code if e.response else 500,
            detail=error_text
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        logger.error(f"Connection error in streaming upload: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Client manager unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in streaming upload: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )
