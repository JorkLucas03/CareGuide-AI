"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Avatar, AvatarFallback } from "../components/ui/avatar";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { ScrollArea } from "../components/ui/scroll-area";
import { 
  Send, 
  Activity, 
  Shield, 
  MapPin, 
  User, 
  Bot, 
  Sparkles, 
  Clock, 
  DollarSign, 
  Navigation,
  HeartPulse,
  AlertCircle
} from "lucide-react";

type CostBreakdown = {
  base: number;
  coverage: number;
  copay: number;
};

type Hospital = {
  id: string;
  name: string;
  address: string;
  distanceKm: number;
  tier: string;
  estimatedCost?: CostBreakdown | null;
};

type BestOption = {
  hospitalId: string;
  hospitalName: string;
  address: string;
  tier: string;
  estimatedCost: CostBreakdown;
  reason: string;
};

type ChatResponse = {
  id: string;
  sessionId?: string;
  reply: string;
  urgencyLevel: 1 | 2 | 3 | 4 | 5;
  specialty: string;
  latencyMs: number;
  cost: CostBreakdown;
  showCost?: boolean;
  hospitals: Hospital[];
  bestOption?: BestOption | null;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type InsurancePolicy = {
  id?: number;
  provider_name?: string;
  tier?: string;
  deductible?: number;
  max_out_of_pocket?: number;
};

type PlanOption = {
  value: string;
  label: string;
  description: string;
};

const urgencyMap: Record<ChatResponse["urgencyLevel"], {
  label: string;
  ring: string;
  text: string;
  icon: React.ReactNode;
}> = {
  1: { label: "Rutina", ring: "from-emerald-500/70 to-emerald-500/10", text: "text-emerald-300", icon: <HeartPulse className="h-6 w-6 text-emerald-300" /> },
  2: { label: "Atencion", ring: "from-lime-400/70 to-lime-400/10", text: "text-lime-300", icon: <Activity className="h-6 w-6 text-lime-300" /> },
  3: { label: "Moderado", ring: "from-amber-400/80 to-amber-400/10", text: "text-amber-300", icon: <AlertCircle className="h-6 w-6 text-amber-300" /> },
  4: { label: "Alto", ring: "from-orange-500/80 to-orange-500/10", text: "text-orange-300", icon: <AlertCircle className="h-6 w-6 text-orange-300" /> },
  5: { label: "Urgente", ring: "from-rose-500/90 to-rose-500/10", text: "text-rose-300", icon: <Activity className="h-6 w-6 text-rose-300 animate-pulse" /> },
};

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("es-EC", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

const formatLatency = (value: number) => `${(value / 1000).toFixed(2)}s`;
const quickPrompts = [
  { text: "Recomendacion de hospital para chequeo general", icon: <MapPin className="h-4 w-4 mr-2" /> },
  { text: "Tengo dolor de pecho hace 20 minutos", icon: <Activity className="h-4 w-4 mr-2" /> },
  { text: "Que significa seguro Oro, Plata y Bronce", icon: <Shield className="h-4 w-4 mr-2" /> },
  { text: "Hospitales en Manta que aceptan seguro Plata", icon: <Navigation className="h-4 w-4 mr-2" /> },
];

const PLAN_TIER_ORDER = ["Oro", "Plata", "Bronce"];

const DEFAULT_PLAN_OPTIONS: PlanOption[] = [
  { value: "Oro", label: "Oro", description: "Cobertura alta" },
  { value: "Plata", label: "Plata", description: "Cobertura media" },
  { value: "Bronce", label: "Bronce", description: "Cobertura basica" },
  { value: "Sin seguro", label: "Sin seguro", description: "Pago particular" },
];

const STORAGE_TTL_MS = 1000 * 60 * 60 * 4;
const STORAGE_KEYS = {
  messages: "careguide_messages",
  response: "careguide_response",
  sessionId: "careguide_session_id",
  insuranceTier: "careguide_insurance_tier",
  lastActive: "careguide_last_active",
};

const parseStoredJson = <T,>(value: string | null, fallback: T): T => {
  if (!value) return fallback;

  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAttemptedMessage, setLastAttemptedMessage] = useState<string | null>(null);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [insuranceTier, setInsuranceTier] = useState<string | null>(null);
  const [planLocked, setPlanLocked] = useState(false);
  const [planOptions, setPlanOptions] = useState<PlanOption[]>(DEFAULT_PLAN_OPTIONS);
  const [mounted, setMounted] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const touchActivity = useCallback(() => {
    if (!mounted) return;
    localStorage.setItem(STORAGE_KEYS.lastActive, String(Date.now()));
  }, [mounted]);

  const clearStoredSession = useCallback(() => {
    Object.values(STORAGE_KEYS).forEach((key) => {
      localStorage.removeItem(key);
    });
  }, []);

  const resetSessionState = async () => {
    setMessages([]);
    setInput("");
    setLoading(false);
    setError(null);
    setLastAttemptedMessage(null);
    setResponse(null);
    setSessionId(null);
    setInsuranceTier(null);
    setPlanLocked(false);
    if (mounted) {
      clearStoredSession();
    }

    try {
      await fetch("/api/session/reset", { method: "POST" });
    } catch {
      // Best-effort session cleanup.
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setMounted(true);

      const lastActiveRaw = localStorage.getItem(STORAGE_KEYS.lastActive);
      if (lastActiveRaw) {
        const lastActive = Number(lastActiveRaw);
        if (Number.isFinite(lastActive) && Date.now() - lastActive > STORAGE_TTL_MS) {
          clearStoredSession();
          return;
        }
      }

      const savedMessages = parseStoredJson<Message[]>(
        localStorage.getItem(STORAGE_KEYS.messages),
        [],
      );
      const savedResponse = parseStoredJson<ChatResponse | null>(
        localStorage.getItem(STORAGE_KEYS.response),
        null,
      );
      const savedSessionId = localStorage.getItem(STORAGE_KEYS.sessionId);
      const savedTier = localStorage.getItem(STORAGE_KEYS.insuranceTier);

      if (savedMessages.length) setMessages(savedMessages);
      if (savedResponse) setResponse(savedResponse);
      if (savedSessionId) setSessionId(savedSessionId);
      if (savedTier) {
        setInsuranceTier(savedTier);
        setPlanLocked(true);
      }
    }, 0);

    return () => window.clearTimeout(timer);
  }, [clearStoredSession]);

  useEffect(() => {
    if (mounted) {
      localStorage.setItem(STORAGE_KEYS.messages, JSON.stringify(messages));
      if (messages.length) {
        touchActivity();
      }
    }
  }, [messages, mounted, touchActivity]);

  useEffect(() => {
    if (mounted && response) {
      localStorage.setItem(STORAGE_KEYS.response, JSON.stringify(response));
      touchActivity();
    }
  }, [response, mounted, touchActivity]);

  useEffect(() => {
    if (mounted && sessionId) {
      localStorage.setItem(STORAGE_KEYS.sessionId, sessionId);
    }
  }, [sessionId, mounted]);

  useEffect(() => {
    if (!mounted) return;
    if (insuranceTier) {
      localStorage.setItem(STORAGE_KEYS.insuranceTier, insuranceTier);
      touchActivity();
    } else {
      localStorage.removeItem(STORAGE_KEYS.insuranceTier);
    }
  }, [insuranceTier, mounted, touchActivity]);

  useEffect(() => {
    let isActive = true;

    const loadPolicies = async () => {
      try {
        const res = await fetch("/api/insurance-policies", { cache: "no-store" });
        if (!res.ok) return;

        const data = (await res.json()) as { policies?: InsurancePolicy[] };
        const policies = Array.isArray(data.policies) ? data.policies : [];
        if (!policies.length) return;

        const tierMap = new Map<string, PlanOption>();
        policies.forEach((policy) => {
          const tier = typeof policy.tier === "string" ? policy.tier.trim() : "";
          if (!tier) return;
          if (tierMap.has(tier)) return;

          const providerName = (policy.provider_name || tier).trim();
          tierMap.set(tier, {
            value: tier,
            label: providerName,
            description: `Plan ${tier}`,
          });
        });

        const ordered = PLAN_TIER_ORDER.map((tier) => tierMap.get(tier)).filter(Boolean) as PlanOption[];
        const extras = Array.from(tierMap.values()).filter(
          (option) => !PLAN_TIER_ORDER.includes(option.value),
        );

        const combined = [
          ...ordered,
          ...extras,
          { value: "Sin seguro", label: "Sin seguro", description: "Pago particular" },
        ];

        if (isActive && combined.length) {
          setPlanOptions(combined);
        }
      } catch {
        // Keep fallback plan options when offline.
      }
    };

    loadPolicies();

    return () => {
      isActive = false;
    };
  }, []);

  const isHydrated = mounted;
  const activePlan = useMemo(
    () => planOptions.find((plan) => plan.value === insuranceTier),
    [planOptions, insuranceTier],
  );
  const planLabel = activePlan
    ? activePlan.label === activePlan.value
      ? activePlan.label
      : `${activePlan.label} (${activePlan.value})`
    : insuranceTier;
  const hasTier = isHydrated && Boolean(insuranceTier);
  const isPlanLocked = isHydrated && planLocked && Boolean(insuranceTier);
  const disablePrompts = isHydrated ? !hasTier : false;
  const disableInput = isHydrated ? loading || !hasTier : false;
  const disableSend = isHydrated ? loading || !input.trim() || !hasTier : false;

  const urgency = useMemo(() => {
    if (!response) return null;
    return urgencyMap[response.urgencyLevel];
  }, [response]);

  const lowestCopay = useMemo(() => {
    if (!response?.hospitals?.length) return null;
    const values = response.hospitals
      .map((hospital) => hospital.estimatedCost?.copay)
      .filter((value): value is number => typeof value === "number");
    if (!values.length) return null;
    return Math.min(...values);
  }, [response]);

  const isHighUrgency = (response?.urgencyLevel ?? 0) >= 4;
  const showCost = response?.showCost ?? !isHighUrgency;
  const costBase = showCost ? response?.cost.base ?? 0 : 0;
  const costCoverage = showCost ? response?.cost.coverage ?? 0 : 0;
  const costCopay = showCost ? response?.cost.copay ?? 0 : 0;
  const costTotal = showCost ? Math.max(costBase, costCoverage + costCopay, 1) : 1;
  const coveragePct = showCost ? Math.min(100, (costCoverage / costTotal) * 100) : 0;
  const copayPct = showCost ? Math.min(100 - coveragePct, (costCopay / costTotal) * 100) : 0;
  const bestOption = response?.bestOption ?? null;

  useEffect(() => {
    if (!bottomRef.current) return;
    bottomRef.current.scrollIntoView({ behavior: messages.length ? "smooth" : "auto" });
  }, [messages, loading]);

  const handleQuickPrompt = (prompt: string) => {
    setInput(prompt);
    inputRef.current?.focus();
  };

  const renderMessageContent = (message: Message) => {
    if (message.role === "user") {
      return message.content;
    }

    const parts = message.content
      .split(/\n+/)
      .map((part) => part.trim())
      .filter(Boolean);

    if (!parts.length) {
      return message.content;
    }

    return (
      <div className="space-y-3">
        {parts.map((part, index) => (
          <p key={`${message.id}-${index}`} className="text-base leading-7">
            {part}
          </p>
        ))}
      </div>
    );
  };

  const sendMessage = async (overrideText?: string | React.MouseEvent | React.KeyboardEvent) => {
    const textToSend = typeof overrideText === "string" ? overrideText : input;
    const trimmed = textToSend.trim();
    if (!trimmed || loading) return;

    if (!insuranceTier) {
      setError("Selecciona tu plan antes de enviar sintomas.");
      return;
    }

    setError(null);
    setLastAttemptedMessage(trimmed);

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
    };

    setMessages((prev) => {
      if (typeof overrideText === "string") {
        const last = prev[prev.length - 1];
        if (last?.role === "user" && last.content === trimmed) {
          return prev;
        }
      }
      return [...prev, userMessage];
    });

    if (typeof overrideText !== "string" || input.trim() === trimmed) {
      setInput("");
    }

    setLoading(true);
    touchActivity();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          message: trimmed,
          sessionId: sessionId,
          insuranceTier: insuranceTier,
        }),
      });

      if (!res.ok) throw new Error("Request failed");

      const data = (await res.json()) as ChatResponse;

      if (data.sessionId && data.sessionId !== sessionId) {
        setSessionId(data.sessionId);
      }

      const assistantMessage: Message = {
        id: data.id,
        role: "assistant",
        content: data.reply,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setResponse(data);
      setLastAttemptedMessage(null);
    } catch {
      setError("No pudimos conectar con el asistente. Revisa tu red e intenta otra vez.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-[#0b0f14] to-[#05080a] text-slate-100 selection:bg-emerald-500/30 selection:text-emerald-100 flex flex-col">
      {/* Logos Header */}
      <header className="relative w-full px-4 py-3 sm:px-6 lg:px-8 border-b border-slate-800/40 shrink-0 overflow-hidden">
        {/* Solid Banner Effect */}
        <div className="absolute inset-0 flex z-0">
          {/* ULEAM Colors (Red, White, Green) without blur */}
          <div className="flex-[1.5] bg-rose-600" />
          <div className="flex-1 bg-white" />
          <div className="flex-[1.5] bg-emerald-600" />
        </div>
        
        {/* Header Content */}
        <div className="relative z-10 flex items-center justify-between w-full">
          <div className="flex items-center gap-3">
            {/* ULEAM Logo */}
            <div className="flex items-center justify-center h-10 w-10 sm:h-12 sm:w-12 rounded-xl bg-slate-100 border border-slate-300 shadow-md overflow-hidden relative" title="Logo ULEAM">
              <Image src="/uleam.png" alt="ULEAM" fill sizes="48px" className="object-contain p-1 drop-shadow-md" priority />
            </div>
            <div className="hidden sm:flex flex-col">
              <span className="text-sm font-bold text-white drop-shadow-md leading-tight">Universidad Laica Eloy Alfaro</span>
              <span className="text-[10px] text-white/90 font-medium uppercase tracking-widest drop-shadow-md">de Manabí</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden sm:flex flex-col text-right">
              <span className="text-sm font-bold text-slate-800 leading-tight">Club de Inteligencia Artificial</span>
              <span className="text-[10px] text-slate-600 font-bold uppercase tracking-widest">HackIAthon Manta</span>
            </div>
            {/* Club IA Logo */}
            <div className="flex items-center justify-center h-10 w-10 sm:h-12 sm:w-12 rounded-xl bg-slate-100 border border-slate-300 shadow-md overflow-hidden relative" title="Logo Club IA">
              <Image src="/club-ia.png" alt="Club IA" fill sizes="48px" className="object-cover" priority />
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12 lg:gap-8">
          {/* Main Chat Area */}
          <section className="lg:col-span-6 animate-in fade-in duration-1000 slide-in-from-bottom-4">
          <Card className="flex h-[calc(100vh-9rem)] sm:h-[calc(100vh-10rem)] flex-col border-slate-800/60 bg-slate-950/60 shadow-2xl shadow-emerald-900/10 backdrop-blur-xl">
            <CardHeader className="shrink-0 border-b border-slate-800/40 pb-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 shadow-lg shadow-emerald-500/20">
                    <Activity className="h-6 w-6 text-slate-950" />
                  </div>
                  <div>
                    <CardTitle className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-slate-50 to-slate-400 font-[var(--font-heading)] tracking-tight">
                      CareGuide AI
                    </CardTitle>
                    <p className="text-xs text-slate-200 font-medium">Asistente de Triaje Medico</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 shadow-sm">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                  </span>
                  En linea
                </div>
              </div>
            </CardHeader>
            
            <CardContent className="flex flex-1 flex-col gap-4 p-4 sm:p-6 overflow-hidden min-h-0">
              <div className="shrink-0 rounded-2xl border border-slate-800/60 bg-slate-900/40 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-100">Tu plan de seguro</p>
                    <p className="text-xs text-slate-300">Selecciona un plan para calcular copago y red.</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full border px-3 py-1 text-[11px] uppercase tracking-wider ${
                      hasTier
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                        : "border-amber-500/40 bg-amber-500/10 text-amber-200"
                    }`}>
                      {hasTier ? `Plan: ${planLabel ?? insuranceTier}` : "Plan no seleccionado"}
                    </span>
                    {isPlanLocked ? (
                      <button
                        type="button"
                        onClick={() => void resetSessionState()}
                        className="rounded-full border border-emerald-400/60 bg-emerald-500/10 px-3 py-1 text-[12px] font-semibold text-emerald-200 shadow-sm shadow-emerald-500/10 transition-all hover:border-emerald-300 hover:text-emerald-100"
                      >
                        Nueva consulta
                      </button>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {planOptions.map((plan) => {
                    const isActive = insuranceTier === plan.value;
                    const isDisabled = isPlanLocked && !isActive;
                    return (
                      <button
                        key={plan.value}
                        type="button"
                        onClick={() => {
                          if (isPlanLocked && !isActive) return;
                          setInsuranceTier(plan.value);
                          setPlanLocked(true);
                          setError(null);
                          touchActivity();
                        }}
                        aria-pressed={isActive}
                        disabled={isDisabled}
                        className={`flex flex-col items-start justify-center rounded-xl border px-3 py-2 text-left transition-all ${
                          isActive
                            ? "border-emerald-400/60 bg-emerald-500/20 text-emerald-50"
                            : "border-slate-700/60 bg-slate-950/60 text-slate-200"
                        } ${
                          isDisabled
                            ? "opacity-60 cursor-not-allowed"
                            : "hover:border-emerald-500/40 hover:bg-emerald-500/5"
                        }`}
                      >
                        <span className="text-sm font-semibold">{plan.label}</span>
                        <span className={`text-[10px] ${isActive ? "text-emerald-100/80" : "text-slate-400"}`}>
                          {plan.description}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <ScrollArea className="flex-1 min-h-0 pr-4 -mr-4">
                <div className="flex flex-col gap-6 pb-4">
                  {messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full py-12 text-center animate-in zoom-in-95 duration-700">
                      <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-slate-900/80 border border-slate-800/80 shadow-inner">
                        <Bot className="h-10 w-10 text-emerald-400" />
                      </div>
                      <p className="text-slate-200 font-[var(--font-heading)] text-2xl font-semibold tracking-tight mb-2">
                        Hola, soy CareGuide AI.
                      </p>
                      <p className="text-slate-200/90 max-w-md mx-auto mb-8 text-base">
                        Describe tus sintomas, su duracion y tu nivel de dolor para estimar tu urgencia, copago y encontrar la red medica mas cercana.
                      </p>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
                        {quickPrompts.map((prompt, idx) => (
                          <button
                            key={idx}
                            type="button"
                            onClick={() => handleQuickPrompt(prompt.text)}
                            disabled={disablePrompts}
                            className={`group flex items-center justify-start rounded-xl border p-3 text-left text-sm transition-all ${
                              !disablePrompts
                                ? "border-slate-800/60 bg-slate-900/40 text-slate-200 hover:border-emerald-500/40 hover:bg-emerald-500/5 hover:text-emerald-100 hover:shadow-md"
                                : "border-slate-800/60 bg-slate-900/20 text-slate-500 cursor-not-allowed"
                            }`}
                          >
                            <span className="flex-shrink-0 text-emerald-500 group-hover:text-emerald-400 transition-colors">
                              {prompt.icon}
                            </span>
                            <span className="line-clamp-2">{prompt.text}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    messages.map((message) => (
                      <div
                        key={message.id}
                        className={`flex items-start gap-4 ${
                          message.role === "user" ? "flex-row-reverse" : "flex-row"
                        } animate-in slide-in-from-bottom-2 duration-300`}
                      >
                        <Avatar className={`h-10 w-10 border-2 shrink-0 ${
                          message.role === "user" 
                            ? "border-emerald-500/30 bg-emerald-950" 
                            : "border-slate-700 bg-slate-900"
                        }`}>
                          <AvatarFallback className="bg-transparent text-sm">
                            {message.role === "user" ? <User className="h-5 w-5 text-emerald-400" /> : <Bot className="h-5 w-5 text-slate-200" />}
                          </AvatarFallback>
                        </Avatar>
                        <div
                          className={`relative max-w-[85%] rounded-2xl px-5 py-4 text-base leading-7 shadow-sm sm:max-w-[75%] ${
                            message.role === "user"
                              ? "rounded-tr-sm border border-emerald-500/20 bg-gradient-to-br from-emerald-500/10 to-emerald-900/20 text-emerald-50"
                              : "rounded-tl-sm border border-slate-700/50 bg-slate-800/40 text-slate-100"
                          }`}
                        >
                          {renderMessageContent(message)}
                        </div>
                      </div>
                    ))
                  )}
                  
                  {loading ? (
                    <div className="flex items-start gap-4 animate-in fade-in">
                      <Avatar className="h-10 w-10 border-2 border-slate-700 bg-slate-900 shrink-0">
                        <AvatarFallback className="bg-transparent"><Bot className="h-5 w-5 text-slate-200" /></AvatarFallback>
                      </Avatar>
                      <div className="rounded-2xl rounded-tl-sm border border-slate-800/80 bg-slate-800/40 px-5 py-4 text-base text-slate-200">
                        <span className="inline-flex items-center gap-3">
                          <Sparkles className="h-4 w-4 text-emerald-400 animate-pulse" />
                          Procesando tu consulta
                          <span className="inline-flex gap-1 ml-1">
                            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-400/80" style={{ animationDelay: '0ms' }} />
                            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-400/80" style={{ animationDelay: '150ms' }} />
                            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-400/80" style={{ animationDelay: '300ms' }} />
                          </span>
                        </span>
                      </div>
                    </div>
                  ) : null}
                  <div ref={bottomRef} />
                </div>
              </ScrollArea>

              <div className="pt-2 shrink-0">
                {error ? (
                  <div className="mb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200 animate-in slide-in-from-bottom-2">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="h-5 w-5 text-rose-400 shrink-0" />
                      <span>{error}</span>
                    </div>
                    {lastAttemptedMessage && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => sendMessage(lastAttemptedMessage)}
                        className="shrink-0 border-rose-500/50 bg-rose-500/20 text-rose-200 hover:bg-rose-500/30 hover:text-rose-100"
                        aria-label="Reintentar mensaje"
                      >
                        Reintentar
                      </Button>
                    )}
                  </div>
                ) : null}
                <div className="relative flex items-center shadow-lg">
                  <Input
                    ref={inputRef}
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        sendMessage();
                      }
                    }}
                    placeholder={hasTier ? "Escribe tus sintomas o consulta aqui..." : "Selecciona tu plan para comenzar..."}
                    className="pr-14 min-h-[56px] text-base border-slate-700/60 bg-slate-900/80 text-slate-100 placeholder:text-slate-400 focus-visible:ring-emerald-500/30 focus-visible:border-emerald-500/50 rounded-2xl transition-all"
                    disabled={disableInput}
                    aria-label="Mensaje para el asistente"
                  />
                  <Button
                    size="icon"
                    onClick={() => sendMessage()}
                    disabled={disableSend}
                    className="absolute right-2 h-10 w-10 rounded-xl bg-emerald-500 text-slate-950 hover:bg-emerald-400 disabled:bg-slate-800 disabled:text-slate-400 transition-colors shadow-sm"
                    aria-label="Enviar mensaje"
                  >
                    <Send className="h-5 w-5 ml-0.5" />
                  </Button>
                </div>
                <p className="text-center text-xs text-slate-200 mt-2">
                  La informacion proporcionada es una estimacion, acude a emergencias si tus sintomas son severos.
                </p>
              </div>
            </CardContent>
          </Card>
          </section>

          {/* Right Panel */}
          <aside className="lg:col-span-6 flex flex-col gap-4 h-[calc(100vh-9rem)] sm:h-[calc(100vh-10rem)]">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 shrink-0">
            <Card className="min-h-[170px] border-slate-800/60 bg-slate-950/60 backdrop-blur-xl shadow-xl overflow-hidden relative animate-in fade-in slide-in-from-right-8 duration-700 fill-mode-both" style={{ animationDelay: '150ms' }}>
              <div className={`absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl ${urgency?.ring ?? "from-slate-800 to-transparent"} opacity-20 blur-2xl rounded-bl-full`} />
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base font-[var(--font-heading)] font-semibold flex items-center gap-2">
                    <Activity className="h-4 w-4 text-slate-200" /> Nivel de Urgencia
                  </CardTitle>
                  {response?.latencyMs ? (
                    <span className="flex items-center gap-1 rounded-full border border-slate-700/50 bg-slate-800/50 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-200">
                      <Clock className="h-3 w-3" />
                      {formatLatency(response.latencyMs)}
                    </span>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <div
                    className={`relative flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr ${
                      urgency?.ring ?? "from-slate-800/60 to-slate-800/20 border border-slate-700/50"
                    } ${isHighUrgency ? "animate-pulse shadow-[0_0_30px_rgba(251,113,133,0.2)]" : ""}`}
                  >
                    <div className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-slate-950 shadow-inner">
                      {response ? (
                        <span className="text-2xl font-bold font-[var(--font-heading)] text-white">{response.urgencyLevel}</span>
                      ) : (
                        <span className="text-2xl font-light text-slate-600">-</span>
                      )}
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {urgency?.icon}
                      <p className={`text-lg font-bold ${urgency?.text ?? "text-slate-200"}`}>
                        {urgency?.label ?? "Sin evaluar"}
                      </p>
                    </div>
                    <p className="text-base text-slate-200 leading-snug">
                      {response
                        ? `Basado en tus sintomas reportados.`
                        : "Ingresa tus sintomas para evaluar la urgencia."}
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-slate-800/60 bg-slate-900/50 px-3 py-1.5 text-sm uppercase tracking-wider text-slate-300">
                  <span>Prioridad</span>
                  <span className="text-slate-100">{response ? `${response.urgencyLevel}/5` : "-/5"}</span>
                </div>
              </CardContent>
            </Card>

            <Card className="min-h-[170px] border-slate-800/60 bg-slate-950/60 backdrop-blur-xl shadow-xl overflow-hidden animate-in fade-in slide-in-from-right-8 duration-700 fill-mode-both" style={{ animationDelay: '300ms' }}>
              <CardHeader className="pb-3 border-b border-slate-800/40">
                <CardTitle className="text-base font-[var(--font-heading)] font-semibold flex items-center gap-2">
                  <DollarSign className="h-4 w-4 text-slate-200" /> Copago Estimado
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 flex flex-col gap-4">
              <div className="flex items-center justify-between text-sm rounded-lg bg-slate-900/50 p-2.5 border border-slate-800/50">
                <span className="text-slate-200 flex items-center gap-2">
                  <Shield className="h-4 w-4" /> Especialidad
                </span>
                <span className="font-medium text-slate-200 bg-slate-800 px-2 py-0.5 rounded text-xs">{response?.specialty ?? "General"}</span>
              </div>
              
              {response && !showCost ? (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
                  Por nivel de urgencia no mostramos el copago. Busca atencion medica inmediata.
                </div>
              ) : (
                <>
                  <div className="space-y-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-200">Costo base estimado</span>
                      <span className="font-mono text-slate-200">{response ? formatCurrency(costBase) : "---"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-200">Cobertura del seguro</span>
                      <span className="font-mono text-emerald-400/80">{response ? `-${formatCurrency(costCoverage)}` : "---"}</span>
                    </div>
                    <div className="my-2 h-px w-full bg-slate-800/80" />
                    <div className="flex items-center justify-between text-base">
                      <span className="font-semibold text-slate-200">Tu copago a pagar</span>
                      <span className="font-bold text-emerald-400 font-mono text-lg">
                        {response ? formatCurrency(costCopay) : "---"}
                      </span>
                    </div>
                  </div>

                  <div className="space-y-1.5 mt-2">
                    <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-slate-200">
                      <span>Seguro ({coveragePct.toFixed(0)}%)</span>
                      <span>Copago ({copayPct.toFixed(0)}%)</span>
                    </div>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-800 flex border border-slate-700/50">
                      <div
                        className="h-full bg-emerald-500/80 transition-all duration-1000 ease-out"
                        style={{ width: response ? `${coveragePct}%` : "0%" }}
                      />
                      <div
                        className="h-full bg-slate-500/40 transition-all duration-1000 ease-out"
                        style={{ width: response ? `${copayPct}%` : "0%" }}
                      />
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
          </div>

          {bestOption && showCost ? (
            <Card
              className="shrink-0 border-emerald-500/30 bg-emerald-950/30 backdrop-blur-xl shadow-xl shadow-emerald-950/20 animate-in fade-in slide-in-from-right-8 duration-700 fill-mode-both"
              style={{ animationDelay: '380ms' }}
            >
              <CardHeader className="pb-3 border-b border-emerald-500/20">
                <CardTitle className="text-base font-[var(--font-heading)] font-semibold flex items-center gap-2 text-emerald-100">
                  <DollarSign className="h-4 w-4 text-emerald-300" /> Mejor hospital para tu plan
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_auto] sm:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-lg font-bold text-slate-50">{bestOption.hospitalName}</p>
                      <span className="rounded-full border border-emerald-400/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-emerald-200">
                        {bestOption.tier}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-1 text-sm text-slate-300">{bestOption.address}</p>
                    <p className="mt-2 text-sm leading-6 text-emerald-100/90">{bestOption.reason}</p>
                  </div>
                  <div className="rounded-lg border border-emerald-500/30 bg-slate-950/50 px-4 py-3 text-left sm:text-right">
                    <p className="text-xs uppercase tracking-wider text-slate-400">Copago estimado</p>
                    <p className="mt-1 font-mono text-2xl font-bold text-emerald-300">
                      {formatCurrency(bestOption.estimatedCost.copay)}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {response?.hospitals?.length ? (
            <Card
              className="flex flex-col flex-1 border-slate-800/60 bg-slate-950/60 backdrop-blur-xl shadow-xl overflow-hidden animate-in fade-in slide-in-from-right-8 duration-700 fill-mode-both"
              style={{ animationDelay: '450ms' }}
            >
              <CardHeader className="pb-3 border-b border-slate-800/40">
                <CardTitle className="text-base font-[var(--font-heading)] font-semibold flex items-center gap-2 text-slate-900">
                  <MapPin className="h-4 w-4 text-white" /> Red cercana
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 flex-1 min-h-0">
                <div className="rounded-xl border border-slate-800/60 bg-slate-900/50 flex h-full flex-col">
                  <div className="grid grid-cols-12 gap-2 px-3 py-2 text-[11px] uppercase tracking-wider text-slate-400 border-b border-slate-800/60 shrink-0">
                    <span className="col-span-6">Clinica</span>
                    <span className="col-span-3 text-right">Copago</span>
                    <span className="col-span-3 text-right">Plan</span>
                  </div>
                  <div className="flex-1 overflow-y-auto divide-y divide-slate-800/70">
                    {response.hospitals.map((hospital) => {
                      const copay = hospital.estimatedCost?.copay;
                      const isBestPrice =
                        showCost && typeof copay === "number" && lowestCopay !== null && copay === lowestCopay;

                      return (
                        <div
                          key={`sidebar-${hospital.id}`}
                          className={`grid grid-cols-12 items-center gap-2 px-3 py-2 text-xs text-slate-200 ${
                            isBestPrice ? "bg-slate-800/60" : ""
                          }`}
                        >
                          <div className="col-span-6">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-slate-100">{hospital.name}</span>
                              {isBestPrice ? (
                                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-emerald-200">
                                  Mejor precio
                                </span>
                              ) : null}
                            </div>
                            <p className="text-[11px] text-slate-400 line-clamp-1">{hospital.address}</p>
                          </div>
                          <div className="col-span-3 text-right">
                            <span
                              className={`font-mono ${
                                showCost && typeof copay === "number" ? "text-emerald-300" : "text-slate-500"
                              }`}
                            >
                              {showCost && typeof copay === "number" ? formatCurrency(copay) : "---"}
                            </span>
                            <p className="text-[10px] uppercase tracking-wider text-slate-500">Copago</p>
                          </div>
                          <div className="col-span-3 flex flex-col items-end gap-1">
                            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200 border border-emerald-500/30">
                              {hospital.tier}
                            </span>
                            <span className="text-[10px] text-slate-500 flex items-center gap-1">
                              <Navigation className="h-3 w-3" />
                              {hospital.distanceKm > 0 ? `${hospital.distanceKm.toFixed(1)} km` : "Manta"}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : null}

        </aside>
      </div>
    </div>
    </div>
  );
}
