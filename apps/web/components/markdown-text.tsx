"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { type FC, memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { PrismAsyncLight as SyntaxHighlighterPrism } from "react-syntax-highlighter";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

SyntaxHighlighterPrism.registerLanguage("js", tsx);
SyntaxHighlighterPrism.registerLanguage("jsx", tsx);
SyntaxHighlighterPrism.registerLanguage("ts", tsx);
SyntaxHighlighterPrism.registerLanguage("tsx", tsx);
SyntaxHighlighterPrism.registerLanguage("python", python);
SyntaxHighlighterPrism.registerLanguage("bash", bash);
SyntaxHighlighterPrism.registerLanguage("sh", bash);
SyntaxHighlighterPrism.registerLanguage("json", json);

function useCopyToClipboard(duration = 3000) {
  const [isCopied, setIsCopied] = useState(false);

  const copy = (value: string) => {
    if (!value) return;
    navigator.clipboard.writeText(value).then(() => {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), duration);
    });
  };

  return { isCopied, copy };
}

function CodeHeader({ language, code }: { language?: string; code: string }) {
  const { isCopied, copy } = useCopyToClipboard();

  return (
    <div className="flex items-center justify-between gap-4 rounded-t-lg border-border bg-muted px-4 py-2.5 text-base text-muted-foreground">
      <span className="lowercase font-medium text-sm">{language}</span>
      <button
        type="button"
        onClick={() => copy(code)}
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        {isCopied ? (
          <CheckIcon className="size-4" />
        ) : (
          <CopyIcon className="size-4" />
        )}
      </button>
    </div>
  );
}

function extractTextContent(node: any): string {
  if (node.type === "text") return node.value || "";
  if (node.children) return node.children.map(extractTextContent).join("");
  return "";
}

const components: Record<string, FC<any>> = {
  h1: ({ className, ...props }) => (
    <h1
      className={cn(
        "mb-6 scroll-m-20 text-3xl font-medium tracking-tight last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h2: ({ className, ...props }) => (
    <h2
      className={cn(
        "mt-8 mb-4 scroll-m-20 text-2xl font-medium tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h3: ({ className, ...props }) => (
    <h3
      className={cn(
        "mt-6 mb-3 scroll-m-20 text-xl font-medium tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h4: ({ className, ...props }) => (
    <h4
      className={cn(
        "mt-4 mb-2 scroll-m-20 text-lg font-medium tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  p: ({ className, ...props }) => (
    <p
      className={cn("mt-4 mb-4 leading-7 first:mt-0 last:mb-0", className)}
      {...props}
    />
  ),
  a: ({ className, ...props }) => (
    <a
      className={cn(
        "text-primary underline hover:text-primary/80 underline-offset-4",
        className,
      )}
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  blockquote: ({ className, ...props }) => (
    <blockquote
      className={cn(
        "mt-4 border-l-2 pl-6 italic text-muted-foreground",
        className,
      )}
      {...props}
    />
  ),
  ul: ({ className, ...props }) => (
    <ul
      className={cn("my-4 ml-6 list-disc [&>li]:mt-2", className)}
      {...props}
    />
  ),
  ol: ({ className, ...props }) => (
    <ol
      className={cn("my-4 ml-6 list-decimal [&>li]:mt-2", className)}
      {...props}
    />
  ),
  hr: ({ className, ...props }) => (
    <hr className={cn("my-6 border-border", className)} {...props} />
  ),
  table: ({ className, ...props }) => (
    <div className="my-4 w-full overflow-x-auto">
      <table
        className={cn("w-full border-separate border-spacing-0", className)}
        {...props}
      />
    </div>
  ),
  th: ({ className, ...props }) => (
    <th
      className={cn(
        "bg-muted px-4 py-2.5 text-left text-base font-medium first:rounded-tl-lg last:rounded-tr-lg",
        className,
      )}
      {...props}
    />
  ),
  td: ({ className, ...props }) => (
    <td
      className={cn(
        "border-b border-l px-4 py-2.5 text-base last:border-r",
        className,
      )}
      {...props}
    />
  ),
  strong: ({ className, ...props }) => (
    <strong className={cn("font-medium", className)} {...props} />
  ),
  tr: ({ className, ...props }) => (
    <tr
      className={cn(
        "m-0 border-b p-0 first:border-t [&:last-child>td:first-child]:rounded-bl-lg [&:last-child>td:last-child]:rounded-br-lg",
        className,
      )}
      {...props}
    />
  ),
  pre: ({ node, className, children, ...props }) => {
    const codeNode = node?.children?.find(
      (child: any) => child.tagName === "code",
    );

    if (codeNode) {
      const classNames = codeNode.properties?.className || [];
      const langClass = classNames.find?.((c: string) =>
        c.startsWith("language-"),
      );
      const language = langClass?.replace("language-", "");
      const code = extractTextContent(codeNode).replace(/\n$/, "");

      if (language) {
        return (
          <div className="my-4 min-w-0 max-w-full overflow-hidden rounded-xl bg-muted/60">
            <CodeHeader language={language} code={code} />
            <div className="overflow-x-auto">
              <SyntaxHighlighterPrism
                language={language}
                customStyle={{
                  margin: 0,
                  background: "transparent",
                  padding: "0.875rem 1.125rem",
                  fontSize: "0.8125rem",
                }}
              >
                {code}
              </SyntaxHighlighterPrism>
            </div>
          </div>
        );
      }

      return (
        <pre
          className={cn(
            "my-4 max-w-full overflow-x-auto rounded-xl bg-muted/60 p-4 text-[0.8125rem] leading-relaxed font-mono",
            className,
          )}
        >
          {code}
        </pre>
      );
    }

    return (
      <pre
        className={cn(
          "my-4 max-w-full overflow-x-auto [&>div]:my-0!",
          className,
        )}
        {...props}
      />
    );
  },
  code: ({
    className,
    children,
    ...props
  }: {
    className?: string;
    children: React.ReactNode;
  }) => {
    return (
      <code
        className={cn(
          "rounded bg-muted px-2 py-0.5 text-sm font-mono break-all",
          className,
        )}
        {...props}
      >
        {children}
      </code>
    );
  },
};

const MarkdownTextImpl: FC<{ children: string }> = ({ children }) => {
  return (
    <div className="markdown-content min-w-0 max-w-full overflow-hidden text-base leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
};

export const MarkdownText = memo(MarkdownTextImpl);
