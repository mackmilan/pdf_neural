import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import { useContextStore } from './context'
import type { DocumentResult, DocumentVersion, Field, FormatNorm, NeuralTable, RadioOptionBox } from '../types'

const FIELD_TEXT_FONT_SIZE = 12
const FIELD_TEXT_LINE_HEIGHT = 1.2
const FIELD_TEXT_VERTICAL_PADDING = 4
export const FIELD_TEXT_HEIGHT = Math.ceil(
  FIELD_TEXT_FONT_SIZE * FIELD_TEXT_LINE_HEIGHT + FIELD_TEXT_VERTICAL_PADDING,
)
export const FIELD_CHOICE_WIDTH = 14
export const FIELD_CHOICE_HEIGHT = 18

export function normalizedFieldHeight(field: Pick<Field, 'type'> & Partial<Pick<Field, 'height'>>): number {
  if (field.type === 'checkbox' || field.type === 'radio') return FIELD_CHOICE_HEIGHT
  if (field.type === 'textarea') {
    const height = Number(field.height)
    return Number.isFinite(height) ? Math.max(5, height) : FIELD_TEXT_HEIGHT
  }
  return FIELD_TEXT_HEIGHT
}

export function optionalNumber(value: unknown): number | null {
  return value === '' || value === null || value === undefined ? null : Number(value)
}

function cloneField(field: Field): Field {
  return {
    ...field,
    options: field.options ? [...field.options] : undefined,
    option_boxes: field.option_boxes?.map((box) => ({ ...box })),
  }
}

export function normalizeFieldBox(field: Field): Field {
  const normalized: Field = {
    ...field,
    required: Boolean(field.required),
    height: normalizedFieldHeight(field),
    align: ['left', 'center', 'justify', 'right'].includes(field.align as string) ? field.align : 'left',
  }
  if (normalized.type === 'checkbox' || normalized.type === 'radio') {
    normalized.width = FIELD_CHOICE_WIDTH
    normalized.height = FIELD_CHOICE_HEIGHT
  }
  const min = optionalNumber(field.min)
  const max = optionalNumber(field.max)
  if (normalized.type === 'number' && Number.isFinite(min)) normalized.min = min as number
  else delete normalized.min
  if (normalized.type === 'number' && Number.isFinite(max)) normalized.max = max as number
  else delete normalized.max
  if (normalized.type === 'radio') {
    normalized.options = Array.from(
      new Set((Array.isArray(field.options) ? field.options : []).map((option) => String(option).trim()).filter(Boolean)),
    )
    const existing = Array.isArray(field.option_boxes) ? field.option_boxes : []
    normalized.option_boxes = normalized.options.map((value, index): RadioOptionBox => {
      const box = existing.find((item) => item?.value === value) || existing[index]
      return {
        value,
        page: Number(box?.page) || normalized.page,
        x: Number.isFinite(Number(box?.x)) ? Number(box!.x) : normalized.x + index * 22,
        y: Number.isFinite(Number(box?.y)) ? Number(box!.y) : normalized.y,
        width: FIELD_CHOICE_WIDTH,
        height: FIELD_CHOICE_HEIGHT,
      }
    })
  } else delete normalized.options
  if (normalized.type !== 'radio') delete normalized.option_boxes
  return normalized
}

export function fieldTextAlign(field: Pick<Field, 'align'>): string {
  return ['left', 'center', 'justify', 'right'].includes(field.align as string) ? (field.align as string) : 'left'
}

export function fieldValidationSummary(field: Field): string {
  return [
    field.required ? 'obrigatório' : '',
    field.type === 'number' && Number.isFinite(optionalNumber(field.min)) ? `mín. ${field.min}` : '',
    field.type === 'number' && Number.isFinite(optionalNumber(field.max)) ? `máx. ${field.max}` : '',
    field.type === 'radio' ? `${field.options?.length || 0} opções` : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

export const useDocumentStore = defineStore('document', {
  state: () => ({
    status: '' as string,
    currentJobId: null as string | null,
    currentDocumentId: null as string | null,
    currentDocumentName: '' as string,
    currentCategoryId: null as string | null,
    currentFormatNorm: null as FormatNorm | null,
    currentSingleSubmissionPerUser: false,
    currentAllowDocumentPageSubmission: false,
    currentVersion: null as number | null,
    currentFields: [] as Field[],
    savedFields: [] as Field[],
    formValues: {} as Record<string, any>,
    neuralTables: [] as NeuralTable[],
    previewUrl: '' as string,
    previewHtml: '' as string,
    availableVersions: [] as DocumentVersion[],
    resultVisible: false,
    textEditMode: false,
    textEditDirty: false,
  }),
  getters: {
    isEditableDocument(state): boolean {
      return Boolean(state.currentDocumentId && /^[0-9a-f]{64}$/.test(state.currentDocumentId))
    },
    fieldsChanged(state): boolean {
      return JSON.stringify(state.currentFields) !== JSON.stringify(state.savedFields)
    },
  },
  actions: {
    displayResult(data: DocumentResult, options: { refreshVersions?: boolean } = {}) {
      const result = data.result || data
      const previewUrl = result.preview_url || result.preview || data.preview || ''
      this.currentJobId = (result.job_id as string) || (data.job_id as string) || this.currentJobId
      this.currentDocumentId = (result.document_id as string) || (data.document_id as string) || this.currentDocumentId
      this.currentVersion = Number(result.version || data.version || this.currentVersion) || null
      const metadata = result.metadata || data.metadata || {}
      this.currentDocumentName = metadata.filename || (data as any).filename || this.currentDocumentName || 'Documento'
      this.currentCategoryId =
        result.category_id !== undefined
          ? (result.category_id as string | null) || null
          : data.category_id !== undefined
            ? ((data.category_id as string | null) || null)
            : this.currentCategoryId
      this.currentFormatNorm =
        result.format_norm !== undefined
          ? (result.format_norm as FormatNorm | null) || null
          : data.format_norm !== undefined
            ? ((data.format_norm as FormatNorm | null) || null)
            : this.currentFormatNorm
      this.currentSingleSubmissionPerUser =
        result.single_submission_per_user !== undefined
          ? Boolean(result.single_submission_per_user)
          : data.single_submission_per_user !== undefined
            ? Boolean(data.single_submission_per_user)
            : this.currentSingleSubmissionPerUser
      this.currentAllowDocumentPageSubmission =
        result.allow_document_page_submission !== undefined
          ? Boolean(result.allow_document_page_submission)
          : data.allow_document_page_submission !== undefined
            ? Boolean(data.allow_document_page_submission)
            : this.currentAllowDocumentPageSubmission
      this.currentFields = (result.fields || []).map(normalizeFieldBox)
      this.savedFields = this.currentFields.map(cloneField)
      this.formValues = {}
      this.neuralTables = result.neural_tables || []
      this.previewUrl = previewUrl
      this.resultVisible = true
      this.textEditMode = false
      this.textEditDirty = false
      const refreshVersions = options.refreshVersions ?? true
      if (refreshVersions) {
        this.loadVersions(this.currentVersion ?? undefined).catch((error) => {
          this.status = 'Erro ao carregar versões: ' + (error as Error).message
        })
      }
    },
    async loadPreview() {
      const auth = useAuthStore()
      if (!this.previewUrl) return
      const response = await auth.apiFetch(this.previewUrl)
      if (!response.ok) throw new Error('Não foi possível abrir a prévia autenticada')
      this.previewHtml = await response.text()
    },
    async loadJob(jobId: string) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = 'Carregando documento do histórico...'
      try {
        if (!context.tenantId) throw new Error('Selecione um tenant.')
        const response = await auth.apiFetch(`/api/documents/${jobId}?${context.searchParams}`)
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.displayResult({ ...data, preview: `/jobs/${encodeURIComponent(data.job_id || jobId)}/html/index.html` })
        this.status = 'Documento carregado do histórico'
      } catch (error) {
        this.status = 'Erro ao carregar job: ' + (error as Error).message
      }
    },
    async deleteDocument(jobId: string) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = 'Excluindo documento...'
      try {
        const response = await auth.apiFetch(`/api/documents/${encodeURIComponent(jobId)}?${context.searchParams}`, {
          method: 'DELETE',
        })
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        if (this.currentJobId === jobId || this.currentDocumentId === jobId) {
          this.reset()
        }
        await context.loadHistory()
        this.status = 'Documento excluído.'
      } catch (error) {
        this.status = 'Erro ao excluir: ' + (error as Error).message
      }
    },
    reset() {
      this.currentJobId = null
      this.currentDocumentId = null
      this.currentDocumentName = ''
      this.currentCategoryId = null
      this.currentFormatNorm = null
      this.currentSingleSubmissionPerUser = false
      this.currentAllowDocumentPageSubmission = false
      this.currentFields = []
      this.savedFields = []
      this.previewUrl = ''
      this.previewHtml = ''
      this.resultVisible = false
      this.textEditMode = false
      this.textEditDirty = false
    },
    async saveDocumentName(documentId: string, name: string) {
      const auth = useAuthStore()
      const context = useContextStore()
      const normalized = name.trim()
      if (!normalized) {
        this.status = 'Informe um nome para o documento.'
        return
      }
      this.status = 'Renomeando documento...'
      try {
        const response = await auth.apiFetch(`/api/documents/${encodeURIComponent(documentId)}/name?${context.searchParams}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: normalized }),
        })
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        if (this.currentDocumentId === documentId) this.currentDocumentName = data.name
        await context.loadHistory()
        this.status = `Documento renomeado para "${data.name}".`
      } catch (error) {
        this.status = 'Erro ao renomear: ' + (error as Error).message
      }
    },
    async applyCategory(categoryId: string | null) {
      const auth = useAuthStore()
      const context = useContextStore()
      if (!this.currentDocumentId) {
        this.status = 'Carregue um documento antes de alterar a categoria.'
        return
      }
      try {
        const params = new URLSearchParams({ tenant_id: context.tenantId })
        if (context.groupId) params.set('group_id', context.groupId)
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId)}/category?${params}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category_id: categoryId || null }),
          },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.currentCategoryId = data.category_id || null
        this.status = this.currentCategoryId ? 'Categoria atualizada.' : 'Categoria removida.'
        await context.loadHistory()
      } catch (error) {
        this.status = 'Erro ao atualizar categoria: ' + (error as Error).message
      }
    },
    async applyFormatNorm(formatNorm: FormatNorm | null) {
      const auth = useAuthStore()
      const context = useContextStore()
      if (!this.currentDocumentId) {
        this.status = 'Carregue um documento antes de aplicar uma formatação.'
        return
      }
      this.status = formatNorm ? `Aplicando formatação ${formatNorm.toUpperCase()}...` : 'Removendo formatação...'
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId)}/format-norm?${context.searchParams}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format_norm: formatNorm || null }),
          },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.displayResult(data)
        await context.loadHistory()
        this.status = formatNorm ? `Formatação ${formatNorm.toUpperCase()} aplicada na versão ${data.version}.` : 'Formatação removida.'
      } catch (error) {
        this.status = 'Erro ao aplicar formatação: ' + (error as Error).message
      }
    },
    async setSingleSubmissionPerUser(documentId: string, enabled: boolean) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = 'Atualizando regra de preenchimento...'
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(documentId)}/single-submission?${context.searchParams}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ single_submission_per_user: enabled }),
          },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        if (this.currentDocumentId === documentId) {
          this.currentSingleSubmissionPerUser = Boolean(data.single_submission_per_user)
        }
        await context.loadHistory()
        this.status = enabled
          ? 'Preenchimento único por usuário ativado.'
          : 'Preenchimento único por usuário desativado.'
      } catch (error) {
        this.status = 'Erro ao atualizar regra: ' + (error as Error).message
      }
    },
    async setDocumentPageSubmissionAllowed(documentId: string, enabled: boolean) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = 'Atualizando disponibilidade para preenchimento...'
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(documentId)}/document-page-submission?${context.searchParams}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ allow_document_page_submission: enabled }),
          },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        if (this.currentDocumentId === documentId) {
          this.currentAllowDocumentPageSubmission = Boolean(data.allow_document_page_submission)
        }
        await context.loadHistory()
        this.status = enabled
          ? 'Preenchimento pela página do documento ativado.'
          : 'Preenchimento pela página do documento desativado.'
      } catch (error) {
        this.status = 'Erro ao atualizar disponibilidade: ' + (error as Error).message
      }
    },
    async loadVersions(selectedVersion?: number) {
      const auth = useAuthStore()
      const context = useContextStore()
      if (!this.isEditableDocument) {
        this.availableVersions = []
        return
      }
      const response = await auth.apiFetch(
        `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/versions?${context.searchParams}`,
      )
      const data = await response.json()
      if (!response.ok) throw new Error(data.error || 'Não foi possível carregar as versões')
      this.availableVersions = data
      if (selectedVersion === undefined) this.currentVersion = data[0]?.version ?? null
    },
    async loadVersion(version: number) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = `Carregando versão ${version}...`
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/versions/${version}?${context.searchParams}`,
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.displayResult({ ...data, preview: `/jobs/${encodeURIComponent(data.job_id)}/html/index.html` })
        this.status = `Versão ${version} carregada.`
      } catch (error) {
        this.status = 'Erro ao carregar versão: ' + (error as Error).message
      }
    },
    async setCurrentVersion(version: number) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = 'Atualizando versão padrão...'
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/versions/${version}/current?${context.searchParams}`,
          { method: 'PUT' },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.currentVersion = version
        await this.loadVersions(version)
        await context.loadHistory()
        this.status = `Versão ${version} definida como padrão.`
      } catch (error) {
        this.status = 'Erro ao definir versão padrão: ' + (error as Error).message
      }
    },
    async toggleDeprecatedVersion(version: number, marking: boolean) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = marking ? 'Marcando versão como deprecated...' : 'Restaurando versão...'
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/versions/${version}/deprecated?${context.searchParams}`,
          { method: marking ? 'PUT' : 'DELETE' },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        await this.loadVersions(version)
        this.status = marking ? `Versão ${version} marcada como deprecated.` : `Versão ${version} restaurada.`
      } catch (error) {
        this.status = 'Erro ao atualizar versão: ' + (error as Error).message
      }
    },
    async deleteVersion(version: number) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = `Excluindo versão ${version}...`
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/versions/${version}?${context.searchParams}`,
          { method: 'DELETE' },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        const remaining = this.availableVersions.filter((item) => item.version !== version)
        const next = remaining.find((item) => item.is_current) || remaining[0]
        if (next) {
          const versionResponse = await auth.apiFetch(
            `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/versions/${next.version}?${context.searchParams}`,
          )
          const versionData = await versionResponse.json()
          if (!versionResponse.ok) throw new Error(versionData.error)
          this.displayResult({ ...versionData, preview: `/jobs/${encodeURIComponent(versionData.job_id)}/html/index.html` })
        } else {
          this.resultVisible = false
        }
        await context.loadHistory()
        this.status = `Versão ${data.version} excluída.`
      } catch (error) {
        this.status = 'Erro ao excluir versão: ' + (error as Error).message
      }
    },
    async saveHtmlText(html: string) {
      const auth = useAuthStore()
      const context = useContextStore()
      this.status = 'Salvando textos como nova versão...'
      try {
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentDocumentId!)}/html?${context.searchParams}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ html_content: html, base_version: this.currentVersion }),
          },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.displayResult(data)
        await context.loadHistory()
        this.status = `Textos salvos na versão ${data.version}.`
        return true
      } catch (error) {
        this.status = 'Erro ao salvar textos: ' + (error as Error).message
        return false
      }
    },
    async saveFields() {
      const auth = useAuthStore()
      const context = useContextStore()
      if (!this.currentJobId) return
      try {
        this.currentFields = this.currentFields.map(normalizeFieldBox)
        const response = await auth.apiFetch(
          `/api/documents/${encodeURIComponent(this.currentJobId)}/fields?${context.searchParams}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fields: this.currentFields }),
          },
        )
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.currentFields = data.fields.map(normalizeFieldBox)
        this.savedFields = this.currentFields.map(cloneField)
        this.status = `${this.currentFields.length} campo(s) salvo(s)`
      } catch (error) {
        this.status = 'Erro ao salvar: ' + (error as Error).message
      }
    },
    discardFields() {
      this.currentFields = this.savedFields.map(cloneField)
      this.status = 'Alterações descartadas.'
    },
    async uploadDocument(formData: FormData) {
      const auth = useAuthStore()
      const context = useContextStore()
      if (!context.tenantId) throw new Error('Selecione um tenant antes de converter.')
      formData.set('tenant_id', context.tenantId)
      if (context.groupId) formData.set('group_id', context.groupId)
      if (context.categoryId) formData.set('category_id', context.categoryId)
      const response = await auth.apiFetch('/api/convert', { method: 'POST', body: formData })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      this.displayResult(data)
      this.status = `${data.fields.length} campo(s) · ${data.neural_tables.length} tabela(s) neural(is)`
      await context.loadHistory()
      return data
    },
  },
})
