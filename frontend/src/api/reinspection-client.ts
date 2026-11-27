/** 复检授权 API 客户端：授权签发、交班、实物领还、检查过程、复查结论、缺陷重开。 */
import { fetchJson, request } from './client'

const API = '/api/reinspection'

export interface AuthChainNode {
  顺序: number
  审查人: string
  资格: string
  班组: string
  操作: string
  操作人: string
  时间: string
}

export interface InspectionNote {
  记录人: string
  时间: string
  内容: string
}

export interface ReinspectionAuth {
  id: number
  登记编号: string
  目标缺陷ID: number
  受理班组: string
  授权状态: string
  当前授权人: string
  授权资格: string
  授权链: AuthChainNode[]
  实物领出人: string | null
  领出时间: string | null
  实物在外: boolean
  实物归还人: string | null
  归还时间: string | null
  检查过程: InspectionNote[]
  复查结论: string | null
  结论签发人: string | null
  结论签发资格: string | null
  结论时间: string | null
  有效关闭凭据: boolean
  备注说明: string
}

export interface ReinspectionResult {
  ok: boolean
  message: string
  entry: ReinspectionAuth | null
}

export interface Reviewer {
  账号: string
  班组: string
  资格: string
  角色: string
}

async function post(path: string, body: Record<string, unknown>): Promise<ReinspectionResult> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()) as ReinspectionResult
}

export async function listAuthorizations(
  params: Record<string, string | number> = {},
): Promise<{ ok: boolean; items: ReinspectionAuth[]; total: number }> {
  const query = new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ).toString()
  return fetchJson(`${API}/authorizations?${query}`)
}

export async function getAuthorization(authId: number): Promise<ReinspectionResult> {
  return fetchJson(`${API}/authorizations/${authId}`)
}

export async function getDefectCredential(
  defectId: number,
): Promise<{ ok: boolean; message: string; credential: Record<string, unknown> | null }> {
  return fetchJson(`${API}/defects/${defectId}/credential`)
}

export async function listReviewers(): Promise<{ ok: boolean; items: Reviewer[] }> {
  return fetchJson(`${API}/reviewers`)
}

export function createAuthorization(
  defectId: number,
  team: string,
  reviewer: string,
  operator: string,
): Promise<ReinspectionResult> {
  return post(`${API}/authorizations`, { defect_id: defectId, team, reviewer, operator })
}

export function handover(
  authId: number,
  toReviewer: string,
  operator: string,
): Promise<ReinspectionResult> {
  return post(`${API}/authorizations/${authId}/handover`, {
    to_reviewer: toReviewer,
    operator,
  })
}

export function checkoutPhysical(authId: number, operator: string): Promise<ReinspectionResult> {
  return post(`${API}/authorizations/${authId}/checkout`, { operator })
}

export function returnPhysical(authId: number, operator: string): Promise<ReinspectionResult> {
  return post(`${API}/authorizations/${authId}/return`, { operator })
}

export function addInspectionNote(
  authId: number,
  operator: string,
  note: string,
): Promise<ReinspectionResult> {
  return post(`${API}/authorizations/${authId}/notes`, { operator, note })
}

export function submitConclusion(
  authId: number,
  operator: string,
  conclusion: string,
): Promise<ReinspectionResult> {
  return post(`${API}/authorizations/${authId}/conclusion`, { operator, conclusion })
}

export function voidAuthorization(authId: number, operator: string): Promise<ReinspectionResult> {
  return post(`${API}/authorizations/${authId}/void`, { operator })
}

export function reopenDefect(
  defectId: number,
  operator: string,
): Promise<ReinspectionResult> {
  return post(`${API}/defects/${defectId}/reopen`, { operator })
}
