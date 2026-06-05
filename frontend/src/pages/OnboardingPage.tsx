import { useState } from "react";
import { ArrowRight, FolderOpen, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { setVaultPath, streamSync, SyncEvent } from "@/lib/api";

export function OnboardingPage() {
  const [path, setPath] = useState("");
  const [running, setRunning] = useState(false);
  const [event, setEvent] = useState<SyncEvent | null>(null);
  const [error, setError] = useState("");

  const navigate = useNavigate();
  const vaultPath = path.trim();

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
            <Input
              value={path}
              onChange={(event) => {
                setPath(event.target.value);
                setError("");
              }}
              placeholder="/Users/me/Documents/MyVault"
              disabled={running}
            />

            <Button
              onClick={start}
              disabled={!vaultPath || running}
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