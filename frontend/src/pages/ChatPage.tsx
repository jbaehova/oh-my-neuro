import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Copy, Loader2, Send, StopCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useSessions, newSessionId } from "@/hooks/useSessions";
import { ChatMessage, Citation, streamChat } from "@/lib/api";
import { cn } from "@/lib/utils";

type RichMessage = ChatMessage & {
  citations?: Citation[];
  retrieval_count?: number;
  used_mcp?: boolean;
};

export function ChatPage() {
  const [params, setParams] = useSearchParams();
  const sessions = useSessions();
  const [sessionId, setSessionId] = useState(() => params.get("session") || newSessionId());
  const [messages, setMessages] = useState<RichMessage[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const cancelRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const next = params.get("session") || sessionId;
    setSessionId(next);
    setMessages(sessions.load(next));
    // Session loading is intentionally keyed by the URL params only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  useEffect(() => {
    if (!params.get("session")) {
      setParams({ session: sessionId }, { replace: true });
    }
  }, [params, sessionId, setParams]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, running]);

  const history = useMemo(
    () => messages.filter((m) => m.role === "user" || m.role === "assistant").map(({ role, content }) => ({ role, content })),
    [messages],
  );

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const question = input.trim();
    if (!question || running) return;
    cancelRef.current = false;
    setInput("");
    setRunning(true);
    const nextMessages: RichMessage[] = [...messages, { role: "user", content: question }, { role: "assistant", content: "" }];
    setMessages(nextMessages);

    let answer = "";
    let citations: Citation[] = [];
    let retrievalCount = 0;
    let usedMcp = false;
    try {
      for await (const chunk of streamChat(question, history)) {
        if (cancelRef.current) break;
        if (chunk.kind === "meta") {
          citations = chunk.citations || [];
          retrievalCount = chunk.retrieval_count || 0;
          usedMcp = Boolean(chunk.used_mcp);
        } else if (chunk.kind === "token") {
          answer += chunk.text || "";
          setMessages((current) => replaceLastAssistant(current, { content: answer }));
        } else if (chunk.kind === "error") {
          answer += `\n\n${chunk.text || "오류가 발생했습니다."}`;
          setMessages((current) => replaceLastAssistant(current, { content: answer }));
        } else if (chunk.kind === "done" && chunk.text) {
          answer = chunk.text;
          setMessages((current) => replaceLastAssistant(current, { content: answer }));
        }
      }
      if (cancelRef.current) {
        answer = answer || "응답을 중단했습니다.";
      }
    } catch (error) {
      answer = error instanceof Error ? error.message : "응답 생성 중 오류가 발생했습니다.";
    } finally {
      const finalMessages = replaceLastAssistant(
        nextMessages.map((m) => ({ ...m })),
        { content: answer, citations, retrieval_count: retrievalCount, used_mcp: usedMcp },
      );
      setMessages((current) => {
        const merged = replaceLastAssistant(current, {
          content: answer,
          citations,
          retrieval_count: retrievalCount,
          used_mcp: usedMcp,
        });
        sessions.save(sessionId, merged);
        return merged;
      });
      if (finalMessages.length === 0) {
        sessions.save(sessionId, finalMessages);
      }
      setRunning(false);
    }
  }

  function stop() {
    cancelRef.current = true;
    setRunning(false);
  }

  return (
    <div className="flex min-h-[calc(100vh-2rem)] flex-col">
      <div className="mb-4 flex items-center justify-between border-b pb-4">
        <div>
          <h1 className="text-2xl font-semibold">Chat</h1>
          <p className="text-sm text-muted-foreground">Vault 문서를 검색하고 출처가 붙은 답변을 생성합니다.</p>
        </div>
        <Button variant="outline" onClick={() => navigator.clipboard.writeText(window.location.href)}>
          <Copy className="size-4" />
          Link
        </Button>
      </div>

      <div className="scrollbar-soft flex-1 space-y-5 overflow-y-auto pb-36">
        {messages.length === 0 && (
          <div className="grid min-h-[420px] place-items-center">
            <div className="max-w-xl text-center">
              <h2 className="text-xl font-semibold">질문을 입력하세요</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                문서 근거가 필요한 질문은 검색 파이프라인으로, 간단한 대화는 일반 응답으로 처리됩니다.
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {["최근 동기화된 문서 요약", "계약 관련 조항 찾아줘", "이 문서들의 핵심 리스크"].map((item) => (
                  <Button key={item} variant="secondary" size="sm" onClick={() => setInput(item)}>
                    {item}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((message, index) => (
          <MessageBubble key={`${index}-${message.role}`} message={message} />
        ))}
        {running && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            생성 중
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="fixed bottom-16 left-4 right-4 lg:bottom-4 lg:left-[17rem] lg:right-8">
        <div className="surface mx-auto flex max-w-4xl items-end gap-2 rounded-lg p-2">
          <Textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder="질문을 입력하세요"
            className="max-h-44 min-h-[52px] resize-none border-0 shadow-none focus-visible:ring-0"
          />
          <Button type={running ? "button" : "submit"} size="icon" onClick={running ? stop : undefined}>
            {running ? <StopCircle className="size-4" /> : <Send className="size-4" />}
          </Button>
        </div>
      </form>
    </div>
  );
}

function MessageBubble({ message }: { message: RichMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[860px] rounded-lg px-4 py-3 text-sm leading-7",
          isUser ? "bg-primary text-primary-foreground" : "surface",
        )}
      >
        <div className="whitespace-pre-wrap">{message.content || (!isUser ? "..." : "")}</div>
        {!isUser && (
          <div className="mt-3 flex flex-wrap gap-2">
            {typeof message.retrieval_count === "number" && message.retrieval_count > 0 && (
              <Badge variant="secondary">{message.retrieval_count} chunks</Badge>
            )}
            {message.used_mcp && <Badge variant="warning">MCP</Badge>}
            {message.citations?.map((citation, index) => (
              <Badge key={`${citation.source}-${index}`} variant="outline" className="max-w-full truncate">
                {index + 1}. {citation.source}
                {citation.page ? ` p.${citation.page}` : ""}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function replaceLastAssistant(messages: RichMessage[], patch: Partial<RichMessage>) {
  const next = [...messages];
  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index].role === "assistant") {
      next[index] = { ...next[index], ...patch };
      return next;
    }
  }
  return next;
}
