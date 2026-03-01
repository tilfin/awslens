"""AWS session and client factory."""

import boto3


class AWSContext:
    def __init__(self, profile: str | None, region: str | None,
                 stack_names: list[str] | None = None):
        self.profile = profile
        self.region = region
        self.stack_names = stack_names or []
        kwargs = {}
        if profile:
            kwargs["profile_name"] = profile
        if region:
            kwargs["region_name"] = region
        self.session = boto3.Session(**kwargs)
        self._clients: dict[str, object] = {}

    def client(self, service: str):
        if service not in self._clients:
            self._clients[service] = self.session.client(service)
        return self._clients[service]

    def resolve_region_display(self) -> str:
        if self.region:
            return self.region
        r = self.session.region_name
        return r if r else "unknown"

    def resolve_profile_display(self) -> str:
        if self.profile:
            return self.profile
        return self.session.profile_name or "default"
