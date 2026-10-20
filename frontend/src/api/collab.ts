import { del, get, post, put } from './http'
import type { DocComment, SavedItem, SavedResourceType } from './types'

// ---- favorites / recently viewed ---------------------------------------------------

export const listFavorites = () => get<SavedItem[]>('/me/favorites')
export const getFavoriteState = (type: SavedResourceType, id: string) =>
  get<{ favorited: boolean }>(`/me/favorites/${type}/${id}`)
export const addFavorite = (type: SavedResourceType, id: string) =>
  put<{ favorited: boolean }>(`/me/favorites/${type}/${id}`)
export const removeFavorite = (type: SavedResourceType, id: string) =>
  del<{ favorited: boolean }>(`/me/favorites/${type}/${id}`)
export const listRecent = (limit = 20) => get<SavedItem[]>('/me/recent', { params: { limit } })
export const recordView = (type: SavedResourceType, id: string) =>
  post<void>('/me/recent', { resource_type: type, resource_id: id })

// ---- document comments ---------------------------------------------------------------

export const listComments = (docId: string) => get<DocComment[]>(`/documents/${docId}/comments`)
export const createComment = (
  docId: string,
  body: { body: string; parent_id?: string | null; mentions?: string[] },
) => post<DocComment>(`/documents/${docId}/comments`, body, { silent: true })
export const updateComment = (id: string, body: string) =>
  put<DocComment>(`/comments/${id}`, { body })
export const deleteComment = (id: string) => del<void>(`/comments/${id}`)
export const resolveComment = (id: string, resolved: boolean) =>
  post<DocComment>(`/comments/${id}/resolve`, { resolved })
