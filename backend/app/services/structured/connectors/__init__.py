"""External connectors that pull ERP/MES rows into the local structured mirror."""

from app.services.structured.connectors.base import (
    ConnectorError,
    DeviceRow,
    EquipmentSnapshot,
    SparePartRow,
    StructuredConnectorConfig,
    WorkOrderRow,
    build_connector,
)
from app.services.structured.connectors.csv import CsvEquipmentConnector
from app.services.structured.connectors.rest import RestEquipmentConnector

__all__ = [
    "ConnectorError",
    "CsvEquipmentConnector",
    "DeviceRow",
    "EquipmentSnapshot",
    "RestEquipmentConnector",
    "SparePartRow",
    "StructuredConnectorConfig",
    "WorkOrderRow",
    "build_connector",
]
