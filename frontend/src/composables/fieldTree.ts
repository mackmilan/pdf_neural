import type { Field } from '../types'

export interface FieldTreeEntry {
  field: Field
  index: number
}

export interface FieldTreeGroup {
  kind: 'group'
  groupId: string
  label: string
  fields: FieldTreeEntry[]
}

export interface FieldTreeField extends FieldTreeEntry {
  kind: 'field'
}

export type FieldTreeNode = FieldTreeGroup | FieldTreeField

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
