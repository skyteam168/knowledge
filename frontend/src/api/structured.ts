import { del, get, post, put } from './http'
import type {
  AclEntry,
  EquipDevice,
  EquipSparePart,
  EquipWorkOrder,
  MongoConnectIn,
  MongoListCollectionsOut,
  MongoProbeOut,
  MssqlConnectIn,
  MssqlListTablesOut,
  MssqlProbeOut,
  MysqlConnectIn,
  MysqlListTablesOut,
  MysqlProbeOut,
  PostgresConnectIn,
  PostgresListTablesOut,
  PostgresProbeOut,
  ObjectRelation,
  ObjectRelationCreate,
  Page,
  PageParams,
  StructuredAttrSchema,
  StructuredDomain,
  StructuredDomainCreate,
  StructuredLink,
  StructuredLinkCreate,
  StructuredObjectAcl,
  StructuredRecord,
  StructuredRecordCreate,
  StructuredResolve,
  StructuredSource,
  StructuredSourceCreate,
  StructuredSyncResult,
} from './types'

const BASE = '/admin/structured'

export const listStructuredSources = () => get<StructuredSource[]>(`${BASE}/sources`)

export const createStructuredSource = (body: StructuredSourceCreate) =>
  post<StructuredSource>(`${BASE}/sources`, body)

export const syncStructuredSource = (
  sourceId: string,
  dryRun = false,
  forceFull = false,
) =>
  post<StructuredSyncResult>(`${BASE}/sources/${sourceId}/sync`, undefined, {
    params: { dry_run: dryRun, force_full: forceFull },
  })

export const listMysqlTables = (body: MysqlConnectIn) =>
  post<MysqlListTablesOut>(`${BASE}/mysql/list-tables`, body)

export const probeMysqlTable = (
  body: MysqlConnectIn & { table: string; sample_limit?: number },
) => post<MysqlProbeOut>(`${BASE}/mysql/probe`, body)

export const listPostgresTables = (body: PostgresConnectIn) =>
  post<PostgresListTablesOut>(`${BASE}/postgres/list-tables`, body)

export const probePostgresTable = (
  body: PostgresConnectIn & { table: string; sample_limit?: number },
) => post<PostgresProbeOut>(`${BASE}/postgres/probe`, body)

export const listMongoCollections = (body: MongoConnectIn) =>
  post<MongoListCollectionsOut>(`${BASE}/mongo/list-collections`, body)

export const probeMongoCollection = (
  body: MongoConnectIn & { table: string; sample_limit?: number },
) => post<MongoProbeOut>(`${BASE}/mongo/probe`, body)

export const listMssqlTables = (body: MssqlConnectIn) =>
  post<MssqlListTablesOut>(`${BASE}/mssql/list-tables`, body)

export const probeMssqlTable = (
  body: MssqlConnectIn & { table: string; sample_limit?: number },
) => post<MssqlProbeOut>(`${BASE}/mssql/probe`, body)

export const listStructuredDomains = () => get<StructuredDomain[]>(`${BASE}/domains`)

export const createStructuredDomain = (body: StructuredDomainCreate) =>
  post<StructuredDomain>(`${BASE}/domains`, body)

export const listStructuredRecords = (
  params: PageParams & {
    domain_id: string
    q?: string
    source_id?: string
    object_type?: string
  },
) => get<Page<StructuredRecord>>(`${BASE}/records`, { params })

export const createStructuredRecord = (body: StructuredRecordCreate) =>
  post<StructuredRecord>(`${BASE}/records`, body)

export const listStructuredRecordChildren = (params: {
  parent_object_type: string
  parent_external_id: string
  object_type?: string
  source_id?: string
  limit?: number
}) => get<StructuredRecord[]>(`${BASE}/records/children`, { params })

export const listEquipDevices = (
  params: PageParams & { q?: string; source_id?: string },
) => get<Page<EquipDevice>>(`${BASE}/devices`, { params })

export const listEquipWorkOrders = (
  params: PageParams & { q?: string; source_id?: string },
) => get<Page<EquipWorkOrder>>(`${BASE}/work-orders`, { params })

export const listEquipSpareParts = (
  params: PageParams & { q?: string; source_id?: string },
) => get<Page<EquipSparePart>>(`${BASE}/spare-parts`, { params })

export const listStructuredLinks = (object_type: string, object_id: string) =>
  get<StructuredLink[]>(`${BASE}/links`, { params: { object_type, object_id } })

export const createStructuredLink = (body: StructuredLinkCreate) =>
  post<StructuredLink>(`${BASE}/links`, body)

export const deleteStructuredLink = (linkId: string) => del<void>(`${BASE}/links/${linkId}`)

export const resolveStructured = (params: {
  object_type: string
  external_id: string
  source_id?: string
}) => get<StructuredResolve>(`${BASE}/resolve`, { params })

export const listStructuredAttrSchemas = () =>
  get<StructuredAttrSchema[]>(`${BASE}/attribute-schemas`)

export const getStructuredAttrSchema = (objectType: string) =>
  get<StructuredAttrSchema>(`${BASE}/attribute-schemas/${encodeURIComponent(objectType)}`)

export const listObjectRelations = (params?: {
  relation_type?: string
  from_kind?: string
  from_id?: string
  to_kind?: string
  to_id?: string
  limit?: number
}) => get<ObjectRelation[]>(`${BASE}/object-relations`, { params })

export const createObjectRelation = (body: ObjectRelationCreate) =>
  post<ObjectRelation>(`${BASE}/object-relations`, body)

export const deleteObjectRelation = (relationId: string) =>
  del<void>(`${BASE}/object-relations/${relationId}`)

export const getStructuredObjectAcl = (objectType: string, objectId: string) =>
  get<StructuredObjectAcl>(
    `${BASE}/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/acl`,
  )

export const setStructuredObjectAcl = (
  objectType: string,
  objectId: string,
  entries: AclEntry[],
) =>
  put<StructuredObjectAcl>(
    `${BASE}/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/acl`,
    { entries },
  )
