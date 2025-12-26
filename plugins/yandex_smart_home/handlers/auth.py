from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
import logging
from ..models import YandexUser
from ..service import save_account
from sqlalchemy import select
from ..api.utils import cfg_get

logger = logging.getLogger(__name__)

class AuthHandler:

    def __init__(self, plugin_instance):
        """Initialize handlers with plugin instance reference."""
        self.plugin = plugin_instance
        self.db_session = plugin_instance.db_session_maker if hasattr(plugin_instance, 'db_session_maker') else None
        self.logger = logging.getLogger(__name__)

    async def start_oauth(self, request: Request):
        """Start OAuth process with Yandex."""
        try:
            user_id = await self.plugin._get_current_user_id(request)
            self.logger.info(f"🔍 start_oauth called, config = {self.plugin.config}")
            
            from ..auth.manager import YandexAuthManager
            url = YandexAuthManager.get_yandex_oauth_url(config=self.plugin.config)
            return JSONResponse({"auth_url": url})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        
    async def oauth_callback(self, request: Request):
        """OAuth callback from Yandex."""
        from ..auth.manager import YandexAuthManager
        
        code = request.query_params.get('code')
        if not code and request.method == 'POST':
            form_data = await request.form()
            code = form_data.get('code')
        
        if not code:
            self.logger.warning(f"Callback called without code. Query params: {dict(request.query_params)}")
            raise HTTPException(status_code=400, detail='code required')

        self.logger.info(f"🔍 oauth_callback called with config keys: {list(self.plugin.config.keys()) if self.plugin.config else 'None'}")

        user_id = await self.plugin._get_current_user_id(request)

        # Exchange code for token
        token_resp = await YandexAuthManager.exchange_code_for_token(code, config=self.plugin.config)
        access_token = token_resp.get('access_token') or token_resp.get('token')
        
        if not access_token:
            raise HTTPException(status_code=502, detail='No access_token in token response')

        refresh_token = token_resp.get('refresh_token')
        expires_in = token_resp.get("expires_in")
        ya_user_id = token_resp.get("uid") or token_resp.get("user_id")

        # Persist account: prefer plugin helper if available, else call service directly
        if hasattr(self.plugin, '_save_account') and callable(self.plugin._save_account):
            await self.plugin._save_account(
                user_id=user_id,
                ya_user_id=ya_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=expires_in,
            )
        else:
            self.logger.info("ℹ️ plugin._save_account not available, calling service.save_account directly")
            await save_account(user_id=user_id, ya_user_id=ya_user_id, access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)

        # Auto-discover devices
        discovered_count = 0
        try:
            self.logger.info(f"🔄 Starting automatic device discovery after OAuth callback for user {user_id}")
            discovered_count = await self.plugin.device_manager.discover_devices_for_user(user_id, access_token)
            self.logger.info(f"✅ Discovered {discovered_count} devices for user {user_id}")
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to discover devices after OAuth callback: {e}")

        # Redirect to frontend
        frontend_url = cfg_get('FRONTEND_URL', self.plugin.config, default='https://dev.mishazx.ru')
        redirect_url = f"{frontend_url}/profile"
        
        self.logger.info(f"✅ OAuth callback successful, redirecting to {redirect_url}")
        return RedirectResponse(url=redirect_url, status_code=302)

    async def auth_status(self, request: Request):
        """Get auth status for current user."""        
        user_id = await self.plugin._get_current_user_id(request)
        async with get_session() as db:
            res = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
            acc = res.scalar_one_or_none()
            if not acc:
                return {"linked": False}
            return {
                "linked": True,
                "user_id": acc.user_id,
                "ya_user_id": acc.ya_user_id,
                "expires_at": acc.expires_at.isoformat() if acc.expires_at else None,
                "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
            }

    async def auth_unlink(self, request: Request):
        """Unlink Yandex account for current user."""
        user_id = await self.plugin._get_current_user_id(request)
        async with get_session() as db:
            res = await db.execute(select(YandexUser).where(YandexUser.user_id == user_id))
            acc = res.scalar_one_or_none()
            if acc:
                await db.delete(acc)
                await db.commit()
        return {"status": "ok", "unlinked": True}
