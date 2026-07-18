import type { Field } from './field'

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

export interface EditorFieldEntry extends FieldTreeEntry {
  label?: string
  optionIndex?: number
  optionValue?: string
}

export interface EditorFieldTreeGroup {
  kind: 'group'
  groupType: 'checkbox' | 'radio'
  groupId: string
  label: string
  index?: number
  field?: Field
  fields: EditorFieldEntry[]
}

export interface EditorFieldTreeField extends FieldTreeEntry {
  kind: 'field'
}

export type EditorFieldTreeNode = EditorFieldTreeGroup | EditorFieldTreeField
