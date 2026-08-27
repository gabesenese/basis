export type Language = "pt" | "en";

/*
  Both accounts read the same canonical record. Language is presentation, so
  the dictionary carries only interface words. Nothing here formats or renames
  a measured value, because a number that reads differently in two languages is
  two different numbers.
*/
const DICTIONARY = {
  signIn: { pt: "Entrar", en: "Sign in" },
  signOut: { pt: "Sair", en: "Sign out" },
  email: { pt: "E-mail", en: "Email" },
  password: { pt: "Senha", en: "Password" },
  continue: { pt: "Continuar", en: "Continue" },
  wrongCredentials: {
    pt: "E-mail ou senha incorretos.",
    en: "Email or password is wrong.",
  },
  heroLead: { pt: "Não prevemos.", en: "We do not predict." },
  heroEmphasis: { pt: "Medimos.", en: "We measure." },
  heroBody: {
    pt: "Probabilidade orientada a eventos para EUR/USD. Toda projeção é pontuada contra a moeda honesta, e todo número mostra o quanto é conhecido.",
    en: "Event-driven probability for EUR/USD. Every forecast is scored against the coin flip, and every number shows how well it is known.",
  },
  today: { pt: "Hoje", en: "Today" },
  calendar: { pt: "Calendário", en: "Calendar" },
  study: { pt: "Estudo", en: "Study" },
  context: { pt: "Contexto", en: "Context" },
  instrument: { pt: "Instrumento", en: "Instrument" },
  interface: { pt: "Interface", en: "Interface" },
  theme: { pt: "Tema", en: "Theme" },
  light: { pt: "Claro", en: "Light" },
  dark: { pt: "Escuro", en: "Dark" },
  measured: { pt: "Medido", en: "Measured" },
  modelled: { pt: "Modelado", en: "Modelled" },
  marketOpen: { pt: "Mercado aberto", en: "Market open" },
  marketClosed: { pt: "Mercado fechado", en: "Market closed" },
  nextEvent: { pt: "Próximo evento", en: "Next event" },
  noNextEvent: {
    pt: "Nenhum evento agendado à frente",
    en: "No scheduled event ahead",
  },
  noNextEventBody: {
    pt: "O calendário está coletado e vazio daqui para frente. Rode a coleta se um banco central já publicou datas novas.",
    en: "The calendar is collected and empty from here on. Run the collector if a central bank has published new dates.",
  },
  decision: { pt: "Decisão", en: "Decision" },
  knownSince: { pt: "Conhecido desde", en: "Known since" },
  scheduledFor: { pt: "Agendado para", en: "Scheduled for" },
  costOfTrading: { pt: "Custo de negociar o evento", en: "Cost of trading the event" },
  costLead: {
    pt: "Spread esperado ao redor do comunicado, no percentil 95. A forma foi medida em ticks do Dukascopy e aplicada à linha de base real da OANDA, então todo ponto é modelado e não observado.",
    en: "Expected spread around the statement, at the 95th percentile. The shape was measured on Dukascopy ticks and applied to OANDA's real baseline, so every point is modelled rather than observed.",
  },
  quietBaseline: { pt: "Linha de base calma", en: "Quiet baseline" },
  eventsMeasured: { pt: "Eventos medidos", en: "Events measured" },
  dataHealth: { pt: "Saúde dos dados", en: "Data health" },
  recorder: { pt: "Gravador", en: "Recorder" },
  ticks: { pt: "Ticks", en: "Ticks" },
  bars: { pt: "Barras", en: "Bars" },
  spot: { pt: "À vista", en: "Spot" },
  bid: { pt: "Compra", en: "Bid" },
  ask: { pt: "Venda", en: "Ask" },
  spread: { pt: "Spread", en: "Spread" },
  event: { pt: "Evento", en: "Event" },
  region: { pt: "Região", en: "Region" },
  vintages: { pt: "Versões", en: "Vintages" },
  past: { pt: "Passado", en: "Past" },
  ahead: { pt: "À frente", en: "Ahead" },
  gateTitle: { pt: "O portão da Fase 2", en: "The Phase 2 gate" },
  gateQuestion: {
    pt: "A surpresa padronizada prevê o movimento do EUR/USD em duas horas?",
    en: "Does standardised surprise predict the EUR/USD move at two hours?",
  },
  meetings: { pt: "Reuniões", en: "Meetings" },
  movedTheRange: { pt: "Mexeram na banda", en: "Changed the range" },
  windowLead: { pt: "Distância da janela", en: "Window lead" },
  days: { pt: "dias", en: "days" },
  horizon: { pt: "Horizonte", en: "Horizon" },
  slope: { pt: "Inclinação", en: "Slope" },
  perStdDev: { pt: "pips por desvio padrão", en: "pips per standard deviation" },
  evidence: { pt: "Conta como evidência", en: "Counts as evidence" },
  noEvidence: { pt: "Não separa de zero", en: "Does not clear zero" },
  tradable: { pt: "Conhecível às 14:00", en: "Knowable at 14:00" },
  diagnostic: { pt: "Diagnóstico apenas", en: "Diagnostic only" },
  constrained: { pt: "Surpresa restrita", en: "Constrained surprise" },
  decomposed: { pt: "Decisão e caminho separados", en: "Decision and path apart" },
  repricing: { pt: "Reprecificação da curva", en: "Curve repricing" },
  constrainedNote: {
    pt: "O que o plano chama de surpresa padronizada: a decisão anunciada contra a expectativa precificada na véspera.",
    en: "What the plan names as standardised surprise: the announced decision against the expectation priced the evening before.",
  },
  decomposedNote: {
    pt: "A mesma expectativa entra sozinha, então a inclinação da decisão é lida com o trimestre precificado mantido fixo.",
    en: "The same expectation enters on its own, so the decision slope is read with the priced quarter held fixed.",
  },
  repricingNote: {
    pt: "Como a curva se moveu ao redor do anúncio. Não é conhecível às 14:00, então diagnostica a transmissão em vez de oferecer sinal.",
    en: "How the curve moved across the announcement. Not knowable at 14:00, so it diagnoses transmission rather than offering a signal.",
  },
  eventAfternoon: { pt: "Tarde de FOMC", en: "FOMC afternoon" },
  ordinaryAfternoon: { pt: "Tarde comum", en: "Ordinary afternoon" },
  medianMove: { pt: "movimento absoluto mediano em 2h", en: "median absolute 2h move" },
  robustInterval: { pt: "Intervalo robusto", en: "Robust interval" },
  bootstrapInterval: { pt: "Intervalo bootstrap", en: "Bootstrap interval" },
  leaveOneOut: {
    pt: "Tirando qualquer reunião, a inclinação fica entre",
    en: "Dropping any single meeting leaves the slope between",
  },
  surpriseVsResponse: {
    pt: "Reprecificação contra resposta de duas horas",
    en: "Repricing against the two hour response",
  },
  positioning: { pt: "Posicionamento", en: "Positioning" },
  positioningLead: {
    pt: "Posição líquida não comercial em contratos de EURO FX. Publicado às sextas para posições de terça, então cada ponto só era conhecível dias depois do instante que descreve.",
    en: "Non-commercial net position in EURO FX contracts. Published Friday for Tuesday positions, so each point only became knowable days after the instant it describes.",
  },
  netPosition: { pt: "Posição líquida", en: "Net position" },
  contracts: { pt: "contratos", en: "contracts" },
  openInterest: { pt: "Contratos em aberto", en: "Open interest" },
  long: { pt: "Comprado", en: "Long" },
  short: { pt: "Vendido", en: "Short" },
  ago: { pt: "atrás", en: "ago" },
  never: { pt: "nunca", en: "never" },
  ticksWritten: { pt: "ticks gravados", en: "ticks written" },
  since: { pt: "desde", en: "since" },
  reconnects: { pt: "reconexões", en: "reconnects" },
  recorderNeverRan: {
    pt: "Sem batimento. O gravador nunca rodou nesta máquina.",
    en: "No heartbeat. The recorder has never run on this machine.",
  },
  newestBar: { pt: "barra M1 mais recente", en: "newest M1 bar" },
  lastTick: { pt: "último tick", en: "last tick" },
  heartbeat: { pt: "batimento", en: "heartbeat" },
  loading: { pt: "Lendo", en: "Reading" },
  failed: { pt: "Não foi possível ler", en: "Could not read" },
  retry: { pt: "Tentar de novo", en: "Try again" },
  noSignalScreens: {
    pt: "Sinais, planos e calibragem aparecem quando o motor existir. Nada aqui é preenchido com exemplo.",
    en: "Signals, plans and calibration appear once the engine exists. Nothing here is filled with an example.",
  },
} as const;

export type Key = keyof typeof DICTIONARY;

export function translate(language: Language, key: Key): string {
  return DICTIONARY[key][language];
}
