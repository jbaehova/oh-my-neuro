import { useEffect, useState } from "react";

const KEY = "omn-theme";

export function useTheme() {
  const [dark, setDark] = useState(() => localStorage.getItem(KEY) === "dark");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem(KEY, dark ? "dark" : "light");
  }, [dark]);

  return { dark, setDark };
}

