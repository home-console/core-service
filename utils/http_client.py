"""
HTTP client utilities for communicating with client-manager service.
"""
import os
import json
import random
import string
import http.client
from typing import Any, Dict
from fastapi import HTTPException


def _http_json(
    method: str,
    url: str,
    body: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
    timeout: float = 15.0
) -> Any:
    """
    Make a JSON HTTP request to client-manager service.
    
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
    from urllib.parse import urlparse as _parse
    b = _parse(base)
    scheme = (b.scheme or "http").lower()
    host = b.hostname or "127.0.0.1"
    port = b.port or (443 if scheme == "https" else 80)
    path = url
    if not path.startswith("/"):
        path = "/" + path
        
    if scheme == "https":
        import ssl
        ctx = ssl.create_default_context()
        # Dev mode: disable certificate verification inside docker network
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        
    try:
        payload = None
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        if body is not None:
            payload = json.dumps(body)
        conn.request(method.upper(), path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        text = data.decode("utf-8") if data else ""
        if 200 <= resp.status < 300:
            return json.loads(text) if text else None
        raise HTTPException(status_code=resp.status, detail=text or "Upstream error")
    except (TimeoutError, ConnectionError, OSError) as e:
        raise HTTPException(status_code=503, detail=f"Client manager unavailable: {str(e)}")
    finally:
        try:
            conn.close()
        except:
            pass


def _http_multipart(
    path: str,
    fields: Dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    file_content_type: str = "application/octet-stream",
    timeout: float = 30.0
) -> Any:
    """
    Send a multipart/form-data POST to client-manager.
    This is a minimal implementation suitable for small-to-medium files in dev.
    
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
    from urllib.parse import urlparse as _parse
    b = _parse(base)
    scheme = (b.scheme or "http").lower()
    host = b.hostname or "127.0.0.1"
    port = b.port or (443 if scheme == "https" else 80)
    if not path.startswith("/"):
        path = "/" + path

    boundary = "----boundary" + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    crlf = "\r\n"
    body_parts = []
    for k, v in (fields or {}).items():
        body_parts.append(f"--{boundary}{crlf}Content-Disposition: form-data; name=\"{k}\"{crlf}{crlf}{v}")

    # file part (headers end with two CRLFs, file bytes follow immediately)
    body_parts.append(f"--{boundary}{crlf}Content-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"{crlf}Content-Type: {file_content_type}{crlf}{crlf}")

    # Join parts with CRLF, then append file bytes, a CRLF and the final boundary.
    body_bytes = crlf.join(body_parts).encode("utf-8") + file_bytes + crlf.encode("utf-8") + f"--{boundary}--{crlf}".encode("utf-8")

    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body_bytes))}

    if scheme == "https":
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)

    try:
        conn.request('POST', path, body=body_bytes, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        text = data.decode("utf-8") if data else ""
        if 200 <= resp.status < 300:
            return json.loads(text) if text else None
        raise HTTPException(status_code=resp.status, detail=text or "Upstream error")
    except (TimeoutError, ConnectionError, OSError) as e:
        raise HTTPException(status_code=503, detail=f"Client manager unavailable: {str(e)}")
    finally:
        try:
            conn.close()
        except:
            pass


def _http_multipart_stream(
    path: str,
    fields: Dict[str, str],
    file_field: str,
    filename: str,
    file_path: str,
    file_content_type: str = "application/octet-stream",
    timeout: float = 30.0
) -> Any:
    """
    Stream a multipart/form-data POST to client-manager using chunked encoding.
    This avoids loading the whole file into memory.
    
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
    from urllib.parse import urlparse as _parse
    b = _parse(base)
    scheme = (b.scheme or "http").lower()
    host = b.hostname or "127.0.0.1"
    port = b.port or (443 if scheme == "https" else 80)
    if not path.startswith("/"):
        path = "/" + path

    boundary = "----boundary" + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    crlf = "\r\n"

    # prepare preamble (fields + file header)
    pre_parts = []
    for k, v in (fields or {}).items():
        pre_parts.append(f"--{boundary}{crlf}Content-Disposition: form-data; name=\"{k}\"{crlf}{crlf}{v}")
    pre_parts.append(f"--{boundary}{crlf}Content-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"{crlf}Content-Type: {file_content_type}{crlf}{crlf}")
    preamble = crlf.join(pre_parts).encode("utf-8")
    epilogue = (crlf + f"--{boundary}--{crlf}").encode("utf-8")

    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Transfer-Encoding": "chunked"}

    if scheme == "https":
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)

    def body_iter():
        yield preamble
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        yield epilogue

    try:
        # Use encode_chunked to stream the iterable body
        conn.request('POST', path, body=body_iter(), headers=hdrs, encode_chunked=True)
        resp = conn.getresponse()
        data = resp.read()
        text = data.decode("utf-8") if data else ""
        if 200 <= resp.status < 300:
            return json.loads(text) if text else None
        raise HTTPException(status_code=resp.status, detail=text or "Upstream error")
    except (TimeoutError, ConnectionError, OSError) as e:
        raise HTTPException(status_code=503, detail=f"Client manager unavailable: {str(e)}")
    finally:
        try:
            conn.close()
        except:
            pass
