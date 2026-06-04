"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

type SwitchProps = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "defaultChecked"
> & {
  checked?: boolean
  defaultChecked?: boolean
  onCheckedChange?: (checked: boolean) => void
  size?: "sm" | "default"
}

function Switch({
  checked,
  className,
  defaultChecked = false,
  disabled,
  onCheckedChange,
  onClick,
  size = "default",
  title,
  type = "button",
  ...props
}: SwitchProps) {
  const [uncontrolledChecked, setUncontrolledChecked] =
    React.useState(defaultChecked)
  const isControlled = checked !== undefined
  const isChecked = isControlled ? checked : uncontrolledChecked
  const rootClassName = cn(
    "peer group/switch relative inline-flex shrink-0 items-center rounded-full border border-transparent transition-all outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-[3px] aria-invalid:ring-destructive/20 data-[size=default]:h-[18.4px] data-[size=default]:w-[32px] data-[size=sm]:h-[14px] data-[size=sm]:w-[24px] dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-checked:bg-primary data-unchecked:bg-input dark:data-unchecked:bg-input/80 data-disabled:cursor-not-allowed data-disabled:opacity-50",
    className
  )
  const thumbClassName =
    "pointer-events-none block rounded-full bg-background ring-0 transition-transform group-data-[size=default]/switch:size-4 group-data-[size=sm]/switch:size-3 group-data-[size=default]/switch:data-checked:translate-x-[calc(100%-2px)] rtl:group-data-[size=default]/switch:data-checked:-translate-x-[calc(100%-2px)] group-data-[size=sm]/switch:data-checked:translate-x-[calc(100%-2px)] rtl:group-data-[size=sm]/switch:data-checked:-translate-x-[calc(100%-2px)] dark:data-checked:bg-primary-foreground group-data-[size=default]/switch:data-unchecked:translate-x-0 rtl:group-data-[size=default]/switch:data-unchecked:-translate-x-0 group-data-[size=sm]/switch:data-unchecked:translate-x-0 rtl:group-data-[size=sm]/switch:data-unchecked:-translate-x-0 dark:data-unchecked:bg-foreground"

  function handleClick(event: React.MouseEvent<HTMLButtonElement>) {
    onClick?.(event)
    if (event.defaultPrevented || disabled) {
      return
    }
    const nextChecked = !isChecked
    if (!isControlled) {
      setUncontrolledChecked(nextChecked)
    }
    onCheckedChange?.(nextChecked)
  }

  const hint =
    title ??
    (typeof props["aria-label"] === "string" ? props["aria-label"] : undefined)

  return (
    <button
      aria-checked={isChecked}
      className={rootClassName}
      data-checked={isChecked ? "" : undefined}
      data-disabled={disabled ? "" : undefined}
      data-size={size}
      data-slot="switch"
      data-unchecked={isChecked ? undefined : ""}
      disabled={disabled}
      onClick={handleClick}
      role="switch"
      title={hint}
      type={type}
      {...props}
    >
      <span data-slot="switch-thumb" className={thumbClassName} />
    </button>
  )
}

export { Switch }
