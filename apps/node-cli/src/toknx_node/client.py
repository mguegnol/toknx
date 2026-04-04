from dataclasses import dataclass

import httpx


@dataclass
class toknXClient:
    api_base_url: str
    api_key: str
    node_token: str

    def _headers(self, *, node: bool = False) -> dict[str, str]:
        token = self.node_token if node else self.api_key
        return {"Authorization": f"Bearer {token}"}

    def get_balance(self) -> dict:
        with httpx.Client(base_url=self.api_base_url, timeout=10.0) as client:
            response = client.get("/account/balance", headers=self._headers())
            response.raise_for_status()
            return response.json()

    def register_node(self, *, committed_models: list[str], hardware_spec: dict, capability_mode: str) -> dict:
        with httpx.Client(base_url=self.api_base_url, timeout=15.0) as client:
            response = client.post(
                "/nodes/register",
                headers=self._headers(node=True),
                json={
                    "committed_models": committed_models,
                    "hardware_spec": hardware_spec,
                    "capability_mode": capability_mode,
                },
            )
            response.raise_for_status()
            return response.json()

    def deregister_node(self, node_id: str) -> dict:
        with httpx.Client(base_url=self.api_base_url, timeout=10.0) as client:
            response = client.post(f"/nodes/{node_id}/deregister", headers=self._headers(node=True))
            response.raise_for_status()
            return response.json()
