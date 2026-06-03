"use client"

import type { ComponentProps } from "react"
import { Streamdown } from "streamdown"

import { cn } from "@/lib/utils"

type RichMarkdownProps = {
  content: string
  className?: string
}

export function RichMarkdown({ content, className }: RichMarkdownProps) {
  return (
    <Streamdown
      className={cn("studio-markdown text-sm leading-relaxed", className)}
      components={{
        a: SafeLink,
      }}
      controls={false}
      dir="auto"
      mode="static"
      skipHtml
    >
      {content}
    </Streamdown>
  )
}

function SafeLink({
  children,
  href,
  ...props
}: ComponentProps<"a"> & { node?: unknown }) {
  return (
    <a
      {...props}
      href={href}
      rel="noopener noreferrer"
      target="_blank"
    >
      {children}
    </a>
  )
}
