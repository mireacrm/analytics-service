"""gRPC-клиенты к соседям."""

import uuid
from dataclasses import dataclass

from mirea.core.v1 import core_pb2, core_pb2_grpc
from mireacrm_common import grpc_client


@dataclass(frozen=True, slots=True)
class Branch:
    id: uuid.UUID
    name: str
    address: str


class CoreClient:
    """Справочник организации. Витрины хранят идентификаторы, названия
    подставляются при выдаче отчёта."""

    def __init__(self, address: str) -> None:
        self._channel = grpc_client.channel(address)
        self._stub = core_pb2_grpc.CoreServiceStub(self._channel)

    async def close(self) -> None:
        await self._channel.close()

    async def branch(self, branch_id: uuid.UUID) -> Branch:
        request = core_pb2.GetBranchRequest(branch_id=str(branch_id))

        async with grpc_client.call("core", "branch", branch_id) as metadata:
            response = await self._stub.GetBranch(request, metadata=metadata)

        item = response.branch
        return Branch(id=uuid.UUID(item.id), name=item.name, address=item.address)
