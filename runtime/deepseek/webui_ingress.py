"""Host-callable automation ingress; never accepts a caller's owner assertion.

Wire AFTER WebUI resolves the automation owner and validates permissions, BEFORE
invoking its existing completion handler. The loader and permission check must
be host functions, not JSON supplied by a chat/tool. This is not an HTTP route.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from .controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION

MODEL_ID = 'trading-operations--deepseek'


class WebUIAutomationIngress:
    def __init__(self, db, *, load_automation, owner_permitted):
        self.db = db
        self.load_automation = load_automation
        self.owner_permitted = owner_permitted

    async def enqueue(self, *, automation_id, authenticated_user, scheduled_at):
        if automation_id not in PHASE_BY_AUTOMATION:
            raise PermissionError('Unrecognised trading automation')
        automation = await self.load_automation(automation_id)
        if automation is None or automation.id != automation_id:
            raise PermissionError('Automation no longer exists')
        if getattr(automation, 'is_active', False) is not True:
            raise PermissionError('Automation is paused')
        if authenticated_user is None or authenticated_user.id != automation.user_id:
            raise PermissionError('Automation owner mismatch')
        if await self.owner_permitted(authenticated_user) is not True:
            raise PermissionError('Automation permission revoked')
        if automation.data.get('model_id') != MODEL_ID:
            raise PermissionError('Unexpected controller model')
        if not isinstance(scheduled_at, datetime) or scheduled_at.tzinfo is None:
            raise ValueError('Host scheduled occurrence timestamp with timezone required')
        # Use the original occurrence, not retry wall time (including midnight).
        market_date = scheduled_at.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        bridge = ControllerPhaseBridge(self.db, lambda principal, aid:
            principal is authenticated_user and aid == automation.id)
        return bridge.enqueue(automation_id=automation_id, market_date=market_date,
                              principal=authenticated_user)


def installed_webui_ingress(db):
    """Bind verified WebUI 0.11.4 APIs inside its authenticated host process."""
    from open_webui.models.automations import Automations
    from open_webui.models.users import Users
    from open_webui.models.config import Config
    from open_webui.utils.access_control import has_permission

    async def permitted(principal):
        # Rehydrate current role/permissions; stale principal objects aren't enough.
        current = await Users.get_user_by_id(principal.id)
        if current is None or current.role not in ('user', 'admin'):
            return False
        return current.role == 'admin' or await has_permission(
            current.id, 'features.automations', await Config.get('user.permissions'))

    return WebUIAutomationIngress(db, load_automation=Automations.get_by_id,
                                  owner_permitted=permitted)
