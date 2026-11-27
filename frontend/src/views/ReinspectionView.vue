<template>
  <section class="page" data-module="reinspection">
    <header class="page-head">
      <div>
        <h2>复检授权</h2>
        <p class="page-desc">
          内审巡查按「目标缺陷 + 受理班组」签发复检授权条，授权不跨缺陷共享；
          一项复检只接收当前授权人的实际结论，不合格处置凭生效「通过」凭据关闭包装缺陷。
        </p>
      </div>
      <div class="page-actions">
        <label class="account-pick">
          当前账号
          <select v-model="operator" data-testid="operator-select">
            <option v-for="r in reviewers" :key="r.账号" :value="r.账号">
              {{ r.账号 }}（{{ r.角色 }} · {{ r.班组 }}）
            </option>
          </select>
        </label>
        <button class="btn primary" data-testid="open-authorize" type="button" @click="openAuthorize">
          签发复检授权条
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">授权条总数</span>
        <strong class="stat-value">{{ rows.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">授权中</span>
        <strong class="stat-value">{{ countByStatus('授权中') }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已完成</span>
        <strong class="stat-value">{{ countByStatus('已完成') }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">生效关闭凭据</span>
        <strong class="stat-value">{{ rows.filter((r) => r.有效关闭凭据).length }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>目标缺陷ID</span>
        <input v-model="filterDefectId" data-testid="filter-defect" placeholder="按缺陷ID过滤" />
      </label>
      <label class="filter-item">
        <span>授权状态</span>
        <input v-model="filterStatus" data-testid="filter-status" placeholder="授权中/已完成/已作废" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="route.query.defectId" class="scope-tip">
      正在查看缺陷 #{{ route.query.defectId }} 的复检授权（权限仅归属该缺陷，不与同巡查其他缺陷共享）
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th>授权编号</th>
          <th>目标缺陷</th>
          <th>受理班组</th>
          <th>当前授权人</th>
          <th>授权状态</th>
          <th>复查结论</th>
          <th>实物领出/归还</th>
          <th>关闭凭据</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id" :data-testid="`row-${row.id}`" :data-status="row.授权状态">
          <td>{{ row.登记编号 }}</td>
          <td>#{{ row.目标缺陷ID }}</td>
          <td>{{ row.受理班组 }}</td>
          <td>{{ row.当前授权人 }}</td>
          <td>
            <span class="status-tag" :class="row.授权状态">{{ row.授权状态 }}</span>
          </td>
          <td>
            <template v-if="row.复查结论">
              {{ row.复查结论 }}（{{ row.结论签发人 }}）
            </template>
            <span v-else class="muted">待签结论</span>
          </td>
          <td>
            <span v-if="row.实物领出人">领出：{{ row.实物领出人 }}</span>
            <span v-else class="muted">未领出</span>
            <br v-if="row.实物归还人" />
            <span v-if="row.实物归还人" class="muted">归还：{{ row.实物归还人 }}</span>
            <span v-else-if="row.实物在外" class="warn-text">实物在外</span>
          </td>
          <td>
            <span v-if="row.有效关闭凭据" class="credential-ok">生效凭据</span>
            <span v-else class="muted">—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`detail-${row.id}`" @click="openDetail(row)">
              核对记录
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="9" class="empty-state">暂无复检授权条，可先为目标缺陷签发授权</td>
        </tr>
      </tbody>
    </table>

    <!-- 签发授权 -->
    <div v-if="showAuthorize" class="modal-backdrop" data-testid="authorize-modal">
      <form class="modal" @submit.prevent="submitAuthorize">
        <h3>签发复检授权条</h3>
        <label class="create-field">
          <span>目标缺陷ID</span>
          <input v-model="authForm.defectId" data-testid="auth-defect-id" required />
        </label>
        <label class="create-field">
          <span>受理班组</span>
          <input v-model="authForm.team" data-testid="auth-team" placeholder="如：包装一班" required />
        </label>
        <label class="create-field">
          <span>被授权审查人</span>
          <select v-model="authForm.reviewer" data-testid="auth-reviewer" required>
            <option v-for="r in reviewerOptions" :key="r.账号" :value="r.账号">
              {{ r.账号 }}（{{ r.班组 }} · {{ r.资格 }}）
            </option>
          </select>
        </label>
        <p class="form-hint">授权条只归属该目标缺陷与受理班组，同巡查的其他缺陷不会共享此授权。</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="showAuthorize = false">取消</button>
          <button class="btn primary" data-testid="submit-authorize" type="submit">确认签发</button>
        </div>
      </form>
    </div>

    <!-- 授权核对与办理抽屉 -->
    <div v-if="detail" class="modal-backdrop" data-testid="detail-modal">
      <div class="modal detail-modal">
        <header class="detail-head">
          <h3>复检授权条 {{ detail.登记编号 }}</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>

        <section class="detail-section">
          <h4>归属与状态</h4>
          <dl class="detail-grid">
            <dt>目标缺陷</dt><dd>#{{ detail.目标缺陷ID }}</dd>
            <dt>受理班组</dt><dd>{{ detail.受理班组 }}</dd>
            <dt>当前授权人</dt><dd>{{ detail.当前授权人 }}</dd>
            <dt>授权状态</dt><dd>{{ detail.授权状态 }}</dd>
            <dt>生效关闭凭据</dt>
            <dd>
              <span v-if="detail.有效关闭凭据" class="credential-ok">是（仅第一份通过结论生效）</span>
              <span v-else>否</span>
            </dd>
          </dl>
        </section>

        <section class="detail-section">
          <h4>授权链（含当时资格与操作责任人）</h4>
          <ol class="chain-list" data-testid="auth-chain">
            <li v-for="node in detail.授权链" :key="node.顺序">
              <strong>{{ node.顺序 }}. {{ node.操作 }} → {{ node.审查人 }}</strong>
              <span class="muted">{{ node.班组 }} · {{ node.资格 }} · 操作人 {{ node.操作人 }} · {{ node.时间 }}</span>
            </li>
          </ol>
        </section>

        <section class="detail-section">
          <h4>实物与检查过程</h4>
          <dl class="detail-grid">
            <dt>实物领出人</dt><dd>{{ detail.实物领出人 ?? '—' }} <span v-if="detail.领出时间" class="muted">{{ detail.领出时间 }}</span></dd>
            <dt>实物归还人</dt><dd>{{ detail.实物归还人 ?? '—' }} <span v-if="detail.归还时间" class="muted">{{ detail.归还时间 }}</span></dd>
          </dl>
          <ul class="note-list">
            <li v-for="(note, idx) in detail.检查过程" :key="idx">
              <strong>{{ note.记录人 }}</strong>
              <span class="muted">{{ note.时间 }}</span>
              <p>{{ note.内容 }}</p>
            </li>
            <li v-if="!detail.检查过程.length" class="muted">暂无检查过程记录</li>
          </ul>
        </section>

        <section v-if="detail.复查结论" class="detail-section">
          <h4>已办理结论</h4>
          <dl class="detail-grid">
            <dt>复查结论</dt><dd>{{ detail.复查结论 }}</dd>
            <dt>结论签发人</dt><dd>{{ detail.结论签发人 }}（{{ detail.结论签发资格 }}）</dd>
            <dt>签发时间</dt><dd>{{ detail.结论时间 }}</dd>
          </dl>
          <p class="form-hint">重新打开已办理复检可核对当时资格与责任人，重复发起不生成另一份有效关闭记录。</p>
        </section>

        <!-- 办理操作区 -->
        <section v-if="detail.授权状态 === '授权中'" class="detail-section action-area" data-testid="action-area">
          <h4>办理操作（当前账号：{{ operator }}）</h4>
          <div class="action-buttons">
            <button class="btn" type="button" @click="doCheckout">领出实物</button>
            <button class="btn" type="button" :disabled="!detail.实物在外" @click="doReturn">归还实物</button>
            <button class="btn" type="button" @click="showNoteForm = !showNoteForm">记录检查过程</button>
            <button class="btn" type="button" @click="showHandoverForm = !showHandoverForm">班长交班</button>
            <button class="btn primary" type="button" @click="doConclusion('通过')">提交「通过」结论</button>
            <button class="btn danger" type="button" @click="doConclusion('不通过')">提交「不通过」结论</button>
            <button class="btn ghost" type="button" @click="doVoid">作废授权</button>
          </div>

          <form v-if="showNoteForm" class="inline-form" @submit.prevent="doAddNote">
            <input v-model="noteText" data-testid="note-input" placeholder="填写检查过程记录" required />
            <button class="btn primary" type="submit">保存检查记录</button>
          </form>

          <form v-if="showHandoverForm" class="inline-form" @submit.prevent="doHandover">
            <select v-model="handoverTarget" data-testid="handover-target" required>
              <option v-for="r in handoverOptions" :key="r.账号" :value="r.账号">
                {{ r.账号 }}（{{ r.班组 }}）
              </option>
            </select>
            <button class="btn primary" type="submit">以班长身份发出交班申请</button>
          </form>
        </section>

        <p v-if="message" class="error-text" data-testid="detail-message">{{ message }}</p>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ rows.length }} 条复检授权条</span>
      <span v-if="message" class="error-text">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  addInspectionNote,
  checkoutPhysical,
  createAuthorization,
  getAuthorization,
  handover,
  listAuthorizations,
  listReviewers,
  returnPhysical,
  submitConclusion,
  voidAuthorization,
  type ReinspectionAuth,
  type Reviewer,
} from '@/api/reinspection-client'

const route = useRoute()

const operator = ref('甲')
const reviewers = ref<Reviewer[]>([])
const rows = ref<ReinspectionAuth[]>([])
const message = ref('')
const filterDefectId = ref(String(route.query.defectId ?? ''))
const filterStatus = ref('')

const showAuthorize = ref(false)
const authForm = ref({ defectId: String(route.query.defectId ?? ''), team: '包装一班', reviewer: '甲' })

const detail = ref<ReinspectionAuth | null>(null)
const showNoteForm = ref(false)
const noteText = ref('')
const showHandoverForm = ref(false)
const handoverTarget = ref('乙')

const reviewerOptions = computed(() => reviewers.value.filter((r) => r.角色 === '审查人'))
const handoverOptions = computed(() =>
  reviewers.value.filter((r) => r.角色 === '审查人' && r.账号 !== detail.value?.当前授权人),
)

function countByStatus(status: string): number {
  return rows.value.filter((r) => r.授权状态 === status).length
}

function resetFilters() {
  filterDefectId.value = ''
  filterStatus.value = ''
  void reload()
}

async function reload() {
  message.value = ''
  try {
    const params: Record<string, string> = {}
    if (filterDefectId.value.trim()) params.defect_id = filterDefectId.value.trim()
    if (filterStatus.value.trim()) params.status = filterStatus.value.trim()
    const payload = await listAuthorizations(params)
    rows.value = payload.items
  } catch (error) {
    message.value = error instanceof Error ? error.message : '复检授权数据读取失败'
  }
}

async function loadReviewers() {
  try {
    const payload = await listReviewers()
    reviewers.value = payload.items
  } catch {
    reviewers.value = []
  }
}

function openAuthorize() {
  authForm.value = {
    defectId: filterDefectId.value || String(route.query.defectId ?? ''),
    team: '包装一班',
    reviewer: '甲',
  }
  showAuthorize.value = true
}

async function submitAuthorize() {
  message.value = ''
  const result = await createAuthorization(
    Number(authForm.value.defectId),
    authForm.value.team,
    authForm.value.reviewer,
    operator.value,
  )
  if (!result.ok) {
    message.value = result.message
    return
  }
  showAuthorize.value = false
  await reload()
}

async function openDetail(row: ReinspectionAuth) {
  message.value = ''
  const result = await getAuthorization(row.id)
  detail.value = result.entry
  showNoteForm.value = false
  showHandoverForm.value = false
}

async function refreshDetail() {
  if (!detail.value) return
  const result = await getAuthorization(detail.value.id)
  detail.value = result.entry
}

async function runDetailAction(fn: () => Promise<{ ok: boolean; message: string }>) {
  message.value = ''
  const result = await fn()
  if (!result.ok) {
    message.value = result.message
    return
  }
  message.value = result.message
  await refreshDetail()
  await reload()
}

function doCheckout() {
  if (!detail.value) return
  return runDetailAction(() => checkoutPhysical(detail.value!.id, operator.value))
}

function doReturn() {
  if (!detail.value) return
  return runDetailAction(() => returnPhysical(detail.value!.id, operator.value))
}

function doAddNote() {
  if (!detail.value) return
  const text = noteText.value
  return runDetailAction(async () => {
    const r = await addInspectionNote(detail.value!.id, operator.value, text)
    noteText.value = ''
    showNoteForm.value = false
    return r
  })
}

function doHandover() {
  if (!detail.value) return
  const target = handoverTarget.value
  return runDetailAction(async () => {
    const r = await handover(detail.value!.id, target, operator.value)
    showHandoverForm.value = false
    return r
  })
}

function doConclusion(conclusion: string) {
  if (!detail.value) return
  return runDetailAction(() =>
    submitConclusion(detail.value!.id, operator.value, conclusion),
  )
}

function doVoid() {
  if (!detail.value) return
  return runDetailAction(() => voidAuthorization(detail.value!.id, operator.value))
}

watch(
  () => route.query.defectId,
  (val) => {
    if (val) {
      filterDefectId.value = String(val)
      void reload()
    }
  },
)

onMounted(async () => {
  await loadReviewers()
  await reload()
})
</script>

<style scoped>
.account-pick {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}
.account-pick select {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.scope-tip {
  background: #eef4ff;
  border-left: 3px solid var(--brand);
  padding: 8px 12px;
  font-size: 13px;
  border-radius: 4px;
}
.status-tag {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.status-tag.授权中 { background: #fef3c7; color: #92400e; }
.status-tag.已完成 { background: #dcfce7; color: #166534; }
.status-tag.已作废 { background: #fee2e2; color: #991b1b; }
.credential-ok { color: #15803d; font-weight: 600; }
.warn-text { color: #b45309; }
.muted { color: var(--muted); font-size: 12px; }
.detail-modal { width: min(760px, 100%); }
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.detail-section {
  border-top: 1px solid var(--border);
  padding: 12px 0;
}
.detail-section h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 120px 1fr 120px 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.chain-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
}
.chain-list li { margin-bottom: 6px; display: flex; flex-direction: column; }
.note-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  font-size: 13px;
}
.note-list li {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 6px;
}
.note-list p { margin: 4px 0 0; }
.action-area { background: #f8fafc; border-radius: 8px; padding: 12px; }
.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn.danger { border-color: #fca5a5; color: #b91c1c; }
.inline-form {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.inline-form input,
.inline-form select {
  flex: 1;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.form-hint { font-size: 12px; color: var(--muted); }
</style>
