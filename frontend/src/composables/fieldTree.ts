import type { EditorFieldTreeGroup, EditorFieldTreeNode, Field, FieldTreeGroup, FieldTreeNode } from '../types'

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
