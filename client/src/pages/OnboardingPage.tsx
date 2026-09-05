import { useEffect, useRef, useState } from "react";
import { ArrowRight, FolderOpen, Loader2, CheckCircle2, XCircle, FileText } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { setVaultPath, streamSync, SyncEvent, validateVaultPath, VaultValidation, browseVaultFolder } from "@/lib/api";

const DEBOUNCE_MS = 600;

export function OnboardingPage() {
  const [path, setPath] = useState("");
  const [running, setRunning] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [event, setEvent] = useState<SyncEvent | null>(null);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState<VaultValidation | null>(null);
  const [validating, setValidating] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const navigate = useNavigate();
  const vaultPath = path.trim();

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!vaultPath) {
      setValidation(null);
      setValidating(false);
      return;
    }

    const controller = new AbortController();
    setValidating(true);
    setValidation(null);
    debounceRef.current = setTimeout(async () => {
      try {
        const result = await validateVaultPath(vaultPath, controller.signal);
        if (controller.signal.aborted) return;
        setValidation(result);
      } catch (exc) {
        if (controller.signal.aborted) return;
        if (exc instanceof DOMException && exc.name === "AbortError") return;
        setValidation(null);
      } finally {
        if (!controller.signal.aborted) {
          setValidating(false);
        }
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      controller.abort();
    };
  }, [vaultPath]);

  async function start() {
    const nextPath = path.trim();

    if (!nextPath) {
      setError("Vault path를 입력해주세요.");
      return;
    }

    if (running) return;

    setError("");
    setRunning(true);
    setEvent({
      kind: "progress",
      file: "",
      stage: "Vault 경로 확인 중",
      fraction: null,
    });

    try {
      await setVaultPath(nextPath);

      setEvent({
        kind: "progress",
        file: "",
        stage: "문서 동기화 준비 중",
        fraction: null,
      });

      for await (const item of streamSync()) {
        setEvent(item);

        if (item.kind === "error") {
          throw new Error(item.text);
        }
      }

      setEvent({
        kind: "done",
      } as SyncEvent);

      navigate("/chat");
    } catch (exc) {
      const message =
        exc instanceof Error
          ? exc.message
          : "Vault 설정 중 오류가 발생했습니다.";

      setError(message);
      setEvent(null);
    } finally {
      setRunning(false);
    }
  }

  async function browse() {
    if (browsing || running) return;
    setBrowsing(true);
    try {
      const selected = await browseVaultFolder();
      if (selected) {
        setPath(selected);
        setError("");
      }
    } catch {
      // 사용자가 취소하거나 다이얼로그 오류 — 조용히 무시
    } finally {
      setBrowsing(false);
    }
  }

  const canStart = !!vaultPath && !running && validation?.valid !== false;

  return (
    <main className="grid min-h-[calc(100vh-2rem)] place-items-center">
      <section className="w-full max-w-2xl">
        <div className="mb-8">
          <div className="mb-3 flex size-11 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <FolderOpen className="size-5" />
          </div>

          <h1 className="text-3xl font-semibold">Vault 설정</h1>

          <p className="mt-2 text-sm text-muted-foreground">
            PDF, DOCX, TXT, MD 문서가 들어 있는 로컬 디렉토리를 지정하면 첫 동기화를 실행합니다.
          </p>
        </div>

        <div className="surface rounded-lg p-4">
          <label className="text-sm font-medium">Vault path</label>

          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Input
                value={path}
                onChange={(e) => {
                  setPath(e.target.value);
                  setError("");
                }}
                placeholder="/Users/me/Documents/MyVault"
                disabled={running}
                className={
                  validation
                    ? validation.valid
                      ? "border-green-500 pr-8 focus-visible:ring-green-500"
                      : "border-destructive pr-8 focus-visible:ring-destructive"
                    : "pr-8"
                }
              />
              <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2">
                {validating && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                {!validating && validation?.valid === true && (
                  <CheckCircle2 className="size-4 text-green-500" />
                )}
                {!validating && validation?.valid === false && (
                  <XCircle className="size-4 text-destructive" />
                )}
              </div>
            </div>

            <Button
              variant="outline"
              onClick={browse}
              disabled={browsing || running}
              aria-label="폴더 선택"
              title="폴더 선택"
            >
              {browsing ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <FolderOpen className="size-4" />
              )}
              탐색
            </Button>

            <Button
              onClick={start}
              disabled={!canStart}
              aria-busy={running}
            >
              {running ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  처리 중...
                </>
              ) : (
                <>
                  <ArrowRight className="size-4" />
                  시작
                </>
              )}
            </Button>
          </div>

          {/* 경로 검증 피드백 */}
          {!running && validation && (
            <div
              className={`mt-2 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
                validation.valid
                  ? "border border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
                  : "border border-destructive/30 bg-destructive/10 text-destructive"
              }`}
            >
              {validation.valid ? (
                <>
                  <FileText className="mt-0.5 size-4 shrink-0" />
                  <span>
                    이 폴더에서{" "}
                    <strong>{validation.doc_count}{validation.truncated ? "+개" : "개"}</strong>의 문서를 찾았습니다.
                    {validation.extensions.length > 0 && (
                      <span className="ml-1 text-xs opacity-75">
                        ({validation.extensions.join(", ")})
                      </span>
                    )}
                    {validation.doc_count === 0 && (
                      <span className="ml-1 text-xs opacity-75">
                        — 지원 형식(PDF, DOCX, TXT, MD)이 없을 수 있습니다.
                      </span>
                    )}
                  </span>
                </>
              ) : (
                <span>{validation.error}</span>
              )}
            </div>
          )}

          {running && (
            <div className="mt-3 text-sm text-muted-foreground">
              요청을 처리하고 있습니다. 잠시만 기다려주세요.
            </div>
          )}

          {error && (
            <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          {event && (
            <div className="mt-4">
              <div className="mb-2 truncate text-xs text-muted-foreground">
                {event.kind === "progress"
                  ? `${event.stage} ${event.file || ""}`
                  : event.kind === "done"
                    ? "완료"
                    : event.text}
              </div>

              <Progress
                value={
                  event.kind === "progress" &&
                  typeof event.fraction === "number"
                    ? event.fraction * 100
                    : event.kind === "done"
                      ? 100
                      : undefined
                }
              />
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
