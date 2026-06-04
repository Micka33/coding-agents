"use client"

import {
  isValidElement,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react"
import {
  CodeBlock,
  Streamdown,
  extractTableDataFromElement,
  tableDataToTSV,
} from "streamdown"
import { CheckIcon, CopyIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
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
        code: CopyableCode,
        table: CopyableTable,
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

type MarkdownCodeProps = ComponentProps<"code"> & {
  node?: unknown
  "data-block"?: unknown
}

function CopyableCode({
  children,
  className,
  node,
  ...props
}: MarkdownCodeProps) {
  void node
  const { "data-block": dataBlock, ...codeProps } = props
  const isBlock = dataBlock !== undefined

  if (!isBlock) {
    return (
      <code
        {...codeProps}
        className={cn(
          "rounded bg-muted px-1.5 py-0.5 font-mono text-sm",
          className
        )}
        data-streamdown="inline-code"
      >
        {children}
      </code>
    )
  }

  const code = trimTrailingNewlines(textFromReactNode(children))
  const language = languageFromClassName(className) || "text"

  return (
    <div className="group/markdown-copy relative">
      <CodeBlock code={code} language={language} />
      <MarkdownCopyButton
        ariaLabel="Copy code block"
        className="absolute top-1.5 right-2"
        getValue={() => code}
      />
    </div>
  )
}

type MarkdownTableProps = ComponentProps<"table"> & {
  node?: unknown
}

function CopyableTable({
  children,
  className,
  node,
  ...props
}: MarkdownTableProps) {
  void node
  const tableRef = useRef<HTMLTableElement>(null)

  return (
    <div
      className="group/markdown-copy relative my-4 flex flex-col gap-2 rounded-lg border border-border bg-sidebar p-2"
      data-streamdown="table-wrapper"
    >
      <div className="border-collapse overflow-x-auto overflow-y-auto rounded-md border border-border bg-background">
        <table
          {...props}
          className={cn("w-full divide-y divide-border", className)}
          data-streamdown="table"
          ref={tableRef}
        >
          {children}
        </table>
      </div>
      <MarkdownCopyButton
        ariaLabel="Copy table for spreadsheet"
        className="absolute top-1 right-1"
        getValue={() => {
          if (!tableRef.current) {
            return ""
          }
          return tableDataToTSV(extractTableDataFromElement(tableRef.current))
        }}
      />
    </div>
  )
}

function MarkdownCopyButton({
  ariaLabel,
  className,
  getValue,
}: {
  ariaLabel: string
  className?: string
  getValue: () => string
}) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    const value = getValue()
    if (!value || !navigator.clipboard?.writeText) {
      return
    }

    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={ariaLabel}
          className={cn(
            "z-10 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within/markdown-copy:opacity-100 sm:group-hover/markdown-copy:opacity-100",
            className
          )}
          onClick={copy}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          {copied ? (
            <CheckIcon className="size-3" />
          ) : (
            <CopyIcon className="size-3" />
          )}
        </Button>
      </TooltipTrigger>
      <TooltipContent>copier</TooltipContent>
    </Tooltip>
  )
}

function SafeLink({
  children,
  href,
  ...props
}: ComponentProps<"a"> & { node?: unknown }) {
  return (
    <a {...props} href={href} rel="noopener noreferrer" target="_blank">
      {children}
    </a>
  )
}

function languageFromClassName(className: string | undefined) {
  return className?.match(/(?:^|\s)language-([^\s]+)/)?.[1] ?? ""
}

function trimTrailingNewlines(value: string) {
  return value.replace(/\n+$/, "")
}

function textFromReactNode(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node)
  }

  if (Array.isArray(node)) {
    return node.map((child) => textFromReactNode(child)).join("")
  }

  if (isValidElement<{ children?: ReactNode }>(node)) {
    return textFromReactNode(node.props.children)
  }

  return ""
}
