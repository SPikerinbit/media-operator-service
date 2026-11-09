import { twMerge } from 'tailwind-merge'
export function cx(...values: Array<string | false | null | undefined>) {
  return twMerge(values.filter(Boolean).join(' '))
}
export const cn = cx
export function sortCx<T>(styles: T): T { return styles }
export const EASE_OUT = [0.16, 1, 0.3, 1] as const
export const SPRING_LAYOUT = { type: 'spring', stiffness: 430, damping: 38 } as const
