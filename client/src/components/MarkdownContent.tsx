import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownContentProps = {
  content: string;
  onWikiLink?: (pageId: string) => void;
  className?: string;
  inline?: boolean;
};

export function MarkdownContent({ content, onWikiLink, className, inline = false }: MarkdownContentProps) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-xl font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="text-lg font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold">{children}</h3>,
          p: ({ children }) => (
            <p className={inline ? "inline leading-6" : "leading-7"}>{children}</p>
          ),
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 text-xs">{children}</code>,
          pre: ({ children }) => <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{children}</pre>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-primary/40 pl-4 text-muted-foreground">{children}</blockquote>
          ),
          a: ({ href, children }) => {
            if (href?.startsWith("wiki://") && onWikiLink) {
              const pageId = decodeURIComponent(href.slice("wiki://".length));
              return (
                <button
                  type="button"
                  onClick={() => onWikiLink(pageId)}
                  className="font-medium text-primary underline underline-offset-4 hover:text-primary/80"
                >
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-4">
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
