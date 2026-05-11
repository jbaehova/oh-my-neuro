export function App() {
  return (
    <main className="grid min-h-screen place-items-center bg-background px-6 text-foreground">
      <section className="w-full max-w-xl rounded-lg border bg-card p-6 shadow-sm">
        <p className="text-sm font-medium text-muted-foreground">OH-MY-NEURO</p>
        <h1 className="mt-2 text-2xl font-semibold">프로젝트 초기 화면</h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          팀원별 구현 브랜치가 합쳐지면 Chat, Vault, Settings 화면과 RAG 기능이 이 앱에 연결됩니다.
        </p>
      </section>
    </main>
  );
}
