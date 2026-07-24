import type {
  EditorFieldTreeGroup,
  EditorFieldTreeNode,
  EditorPageGroup,
  Field,
  FieldPageGroup,
  FieldTreeGroup,
  FieldTreeNode,
} from '../types'

export function isCreatedField(field: Field): boolean {
  return field.source === 'manual'
}

export function isDetectedField(field: Field): boolean {
  return !isCreatedField(field)
}

export function buildFieldTree(fields: Field[]): FieldTreeNode[] {
  const nodes: FieldTreeNode[] = []
  const groups = new Map<string, FieldTreeGroup>()

  fields.forEach((field, index) => {
    const groupId = String(field.group_id || '').trim()
    if (!groupId) {
      nodes.push({ kind: 'field', field, index })
      return
    }

    let group = groups.get(groupId)
    if (!group) {
      group = {
        kind: 'group',
        groupId,
        label: String(field.group_label || '').trim() || 'Grupo de campos',
        fields: [],
      }
      groups.set(groupId, group)
      nodes.push(group)
    }
    group.fields.push({ field, index })
  })

  return nodes
}

export function buildPageFieldTree(fields: Field[]): FieldPageGroup[] {
  const nodes = buildFieldTree(fields)
  const pageMap = new Map<number, FieldPageGroup>()

  nodes.forEach((node) => {
    let page = 1
    const fieldsInNode: Field[] = []

    if (node.kind === 'field') {
      page = Number(node.field.page) || 1
      fieldsInNode.push(node.field)
    } else {
      page = Number(node.fields[0]?.field.page) || 1
      node.fields.forEach((f) => fieldsInNode.push(f.field))
    }

    if (!pageMap.has(page)) {
      pageMap.set(page, {
        page,
        nodes: [],
        totalCount: 0,
        detectedCount: 0,
        createdCount: 0,
      })
    }

    const pageGroup = pageMap.get(page)!
    pageGroup.nodes.push(node)

    const countedFields = new Set<string>()
    fieldsInNode.forEach((field) => {
      if (!countedFields.has(field.name)) {
        countedFields.add(field.name)
        pageGroup.totalCount += 1
        if (isCreatedField(field)) pageGroup.createdCount += 1
        else pageGroup.detectedCount += 1
      }
    })
  })

  return Array.from(pageMap.values()).sort((a, b) => a.page - b.page)
}

export function buildEditorFieldTree(fields: Field[]): EditorFieldTreeNode[] {
  const nodes: EditorFieldTreeNode[] = []
  const groups = new Map<string, EditorFieldTreeGroup>()

  fields.forEach((field, index) => {
    if (field.type === 'radio') {
      nodes.push({
        kind: 'group',
        groupType: 'radio',
        groupId: `radio:${field.name}`,
        label: field.label,
        index,
        field,
        fields: (field.options || []).map((option, optionIndex) => ({
          field,
          index,
          label: option,
          optionIndex,
          optionValue: option,
        })),
      })
      return
    }

    const groupId = field.type === 'checkbox' ? String(field.group_id || '').trim() : ''
    if (!groupId) {
      nodes.push({ kind: 'field', field, index })
      return
    }

    let group = groups.get(groupId)
    if (!group) {
      group = {
        kind: 'group',
        groupType: 'checkbox',
        groupId,
        label: String(field.group_label || 'Grupo de checkboxes'),
        fields: [],
      }
      groups.set(groupId, group)
      nodes.push(group)
    }
    group.fields.push({ field, index })
  })

  return nodes
}

export function buildEditorPageFieldTree(fields: Field[]): EditorPageGroup[] {
  const nodes = buildEditorFieldTree(fields)
  const pageMap = new Map<number, EditorPageGroup>()

  nodes.forEach((node) => {
    let page = 1
    const fieldsInNode: Field[] = []

    if (node.kind === 'field') {
      page = Number(node.field.page) || 1
      fieldsInNode.push(node.field)
    } else {
      if (node.groupType === 'radio' && node.field) {
        page = Number(node.field.page) || Number(node.fields[0]?.field.page) || 1
        fieldsInNode.push(node.field)
      } else {
        page = Number(node.fields[0]?.field.page) || 1
        node.fields.forEach((f) => fieldsInNode.push(f.field))
      }
    }

    if (!pageMap.has(page)) {
      pageMap.set(page, {
        page,
        nodes: [],
        totalCount: 0,
        detectedCount: 0,
        createdCount: 0,
      })
    }

    const pageGroup = pageMap.get(page)!
    pageGroup.nodes.push(node)

    const countedFields = new Set<string>()
    fieldsInNode.forEach((field) => {
      if (!countedFields.has(field.name)) {
        countedFields.add(field.name)
        pageGroup.totalCount += 1
        if (isCreatedField(field)) pageGroup.createdCount += 1
        else pageGroup.detectedCount += 1
      }
    })
  })

  return Array.from(pageMap.values()).sort((a, b) => a.page - b.page)
}
