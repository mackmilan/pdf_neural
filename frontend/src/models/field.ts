export type FieldType =
  | 'text' | 'date' | 'time' | 'email' | 'tel' | 'number' | 'checkbox' | 'radio' | 'textarea' | 'select'

export type FieldAlign = 'left' | 'center' | 'justify' | 'right'

export interface RadioOptionBox {
  value: string
  page: number
  x: number
  y: number
  width: number
  height: number
}

export interface Field {
  name: string
  label: string
  type: FieldType
  page: number
  x: number
  y: number
  width: number
  height: number
  align?: FieldAlign
  mask?: string
  required?: boolean
  min?: number
  max?: number
  options?: string[]
  option_boxes?: RadioOptionBox[]
  group_id?: string
  group_label?: string
  source?: string
  [key: string]: unknown
}

export interface FieldFormState {
  label: string
  type: FieldType
  mask: string
  align: FieldAlign
  required: boolean
  min: string
  max: string
  options: string
}
