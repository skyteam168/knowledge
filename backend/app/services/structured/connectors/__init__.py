"""External connectors that pull ERP/MES rows into the local structured mirror."""

from app.services.structured.connectors.base import (
    ConnectorError,
    DeviceRow,
    EquipmentSnapshot,
    FetchResult,
    IncrementalConfig,
    MysqlConfig,
    SparePartRow,
    StructuredConnectorConfig,
    SyncCursor,
    WorkOrderRow,
    build_connector,
)
from app.services.structured.connectors.csv import CsvEquipmentConnector
from app.services.structured.connectors.mysql import MysqlEquipmentConnector
from app.services.structured.connectors.rest import RestEquipmentConnector

__all__ = [
    "ConnectorError",
    "CsvEquipmentConnector",
    "DeviceRow",
    "EquipmentSnapshot",
    "FetchResult",
    "IncrementalConfig",
    "MysqlConfig",
    "MysqlEquipmentConnector",
    "RestEquipmentConnector",
    "SparePartRow",
    "StructuredConnectorConfig",
    "SyncCursor",
    "WorkOrderRow",
    "build_connector",
]
