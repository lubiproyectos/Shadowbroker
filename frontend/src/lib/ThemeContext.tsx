"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

type Theme = "dark" | "light";
type HudColor = "cyan" | "matrix" | "red";

const ThemeContext = createContext<{
  theme: Theme;
  toggleTheme: () => void;
  hudColor: HudColor;
  cycleHudColor: () => void;
}>({
  theme: "dark",
  toggleTheme: () => {},
  hudColor: "red",
  cycleHudColor: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const [hudColor, setHudColor] = useState<HudColor>("red");

  useEffect(() => {
    const saved = localStorage.getItem("sb-theme") as Theme | null;
    if (saved === "light" || saved === "dark") {
      setTheme(saved);
      document.documentElement.setAttribute("data-theme", saved);
    }
    document.documentElement.setAttribute("data-hud", "red");  
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("sb-theme", next);
    document.documentElement.setAttribute("data-theme", next);
  };

  const cycleHudColor = () => {
    const next = hudColor === "cyan" ? "matrix" : "cyan";
    setHudColor(next);
    localStorage.setItem("sb-hud-color", next);
    document.documentElement.setAttribute("data-hud", next);
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, hudColor, cycleHudColor }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
