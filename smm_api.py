import aiohttp
from config import SMM_API_URL, SMM_API_KEY

class SMMApi:
    def __init__(self):
        self.base_url = SMM_API_URL.rstrip("/")
        self.api_key = SMM_API_KEY
        self.timeout = aiohttp.ClientTimeout(total=15)

    async def _request(self, data):
        try:
            payload = {"key": self.api_key, **data}
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(self.base_url, data=payload) as response:
                    if response.status != 200:
                        return None
                    return await response.json(content_type=None)
        except Exception:
            return None

    async def add_order(self, service_id, link, quantity):
        result = await self._request({
            "action": "add", "service": str(service_id),
            "link": link, "quantity": str(quantity)
        })
        if isinstance(result, dict) and result.get("order") is not None:
            return str(result["order"])
        return None

    async def get_status(self, order_id):
        result = await self._request({"action": "status", "order": str(order_id)})
        if isinstance(result, dict) and "error" not in result:
            return {
                "status": result.get("status"),
                "charge": result.get("charge"),
                "remains": result.get("remains")
            }
        return None

    async def get_multi_status(self, order_ids: list):
        result = await self._request({
            "action": "status", "orders": ",".join(map(str, order_ids))
        })
        if isinstance(result, dict) and "error" not in result:
            return result
        if isinstance(result, list):
            return result
        return None

    async def get_balance(self):
        result = await self._request({"action": "balance"})
        if isinstance(result, dict) and result.get("balance") is not None:
            try:
                return float(result["balance"])
            except (TypeError, ValueError):
                return None
        return None

    async def get_services(self):
        result = await self._request({"action": "services"})
        return result if isinstance(result, list) else None

    async def refill_order(self, order_id):
        result = await self._request({"action": "refill", "order": str(order_id)})
        if isinstance(result, dict) and result.get("refill") is not None:
            return str(result["refill"])
        return None

    async def cancel_orders(self, order_ids: list):
        result = await self._request({
            "action": "cancel", "orders": ",".join(map(str, order_ids))
        })
        return result if isinstance(result, (dict, list)) else None
