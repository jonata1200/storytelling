import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import readline from 'node:readline';
import { chromium } from 'playwright';

const IMAGE_URL = 'https://www.meta.ai/';
const VIBES_URL = 'https://vibes.ai/';
const META_HOME_URL = 'https://www.meta.ai/';
const BROWSER_IDLE_TIMEOUT_MS = Math.max(
  15000,
  Number(process.env.STORYTELLING_BROWSER_IDLE_MS || 90000),
);
const managedSessions = new Map();
const managedContextKeys = new WeakMap();
let bridgeServerMode = false;
// Resolve o filechooser nativo pendente do Vibes (definido por
// uploadFrameIntoDialog antes do clique na área de upload).
let pendingFileChooserResolve = null;

async function inputPayload() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

async function persistentPage(profilePath, headless) {
  const sessionKey = path.resolve(profilePath);
  if (bridgeServerMode) {
    const existing = managedSessions.get(sessionKey);
    if (existing) {
      clearTimeout(existing.idleTimer);
      existing.idleTimer = null;
      try {
        const page = existing.context.pages().find(candidate => !candidate.isClosed())
          || await existing.context.newPage();
        existing.active += 1;
        existing.lastUsedAt = Date.now();
        return { context: existing.context, page };
      } catch {
        await existing.context.close().catch(() => {});
        managedSessions.delete(sessionKey);
      }
    }
  }
  await fs.mkdir(profilePath, { recursive: true });
  const context = await chromium.launchPersistentContext(profilePath, {
    channel: 'chrome',
    headless,
    acceptDownloads: true,
    locale: 'pt-BR',
    viewport: { width: 1440, height: 1000 },
  });
  const page = context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(15000);
  if (bridgeServerMode) {
    managedSessions.set(sessionKey, {
      context,
      active: 1,
      idleTimer: null,
      lastUsedAt: Date.now(),
    });
    managedContextKeys.set(context, sessionKey);
  }
  return { context, page };
}

async function releasePersistentPage(context) {
  if (!bridgeServerMode) {
    await context.close().catch(() => {});
    return;
  }
  const sessionKey = managedContextKeys.get(context);
  const session = sessionKey ? managedSessions.get(sessionKey) : null;
  if (!session || session.context !== context) return;
  session.active = Math.max(0, session.active - 1);
  session.lastUsedAt = Date.now();
  clearTimeout(session.idleTimer);
  session.idleTimer = setTimeout(async () => {
    const current = managedSessions.get(sessionKey);
    if (!current || current.context !== context || current.active > 0) return;
    managedSessions.delete(sessionKey);
    await context.close().catch(() => {});
  }, BROWSER_IDLE_TIMEOUT_MS);
}

async function closePersistentSession(context) {
  // Fluxo de imagens solicitado: abre o navegador, envia o prompt, espera a
  // geração terminar, entrega a imagem e FECHA o navegador imediatamente. A
  // próxima referência repete o ciclo com um navegador novo no MESMO chat
  // (a URL da conversa persistida garante isso), evitando estado acumulado
  // (lazy-load de imagens antigas, abas órfãs, memória) entre gerações.
  // Fechamento PROGRAMÁTICO: o watcher de fechamento manual deve ignorá-lo.
  automationClosingContexts.add(context);
  try {
    if (!bridgeServerMode) {
      await context.close().catch(() => {});
      return;
    }
    const sessionKey = managedContextKeys.get(context);
    const session = sessionKey ? managedSessions.get(sessionKey) : null;
    if (session) {
      clearTimeout(session.idleTimer);
      if (session.context === context) managedSessions.delete(sessionKey);
    }
    if (sessionKey) managedContextKeys.delete(context);
    await context.close().catch(() => {});
  } finally {
    automationClosingContexts.delete(context);
  }
}

async function closeManagedSessions() {
  const sessions = [...managedSessions.values()];
  managedSessions.clear();
  await Promise.all(sessions.map(async session => {
    clearTimeout(session.idleTimer);
    await session.context.close().catch(() => {});
  }));
}

async function loginRequired(page) {
  return await page.getByRole('button', { name: /entrar|log in|sign in/i }).first().isVisible()
    .catch(() => false);
}

async function ensureAuthorized(page, { autoLogin = false } = {}) {
  if (autoLogin && await loginRequired(page)) {
    const login = page.getByRole('button', { name: /entrar|log in|sign in/i }).first();
    await login.click();
    await page.waitForTimeout(3000);
    await settlePage(page);
  }
  if (await loginRequired(page)) {
    throw new Error(
      'Perfil Meta não autorizado. Use “Autorizar Meta” nos Ajustes e conclua o login manual.'
    );
  }
}

async function settlePage(page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1000);
}

async function visibleVideoPromptTextbox(page) {
  const candidates = [
    page.getByRole('textbox', {
      name: /describe (?:a )?video|descreva (?:um )?v[íi]deo/i,
    }).last(),
    page.locator('main [role="textbox"][contenteditable="true"]').last(),
    page.locator('main textarea').last(),
  ];
  for (const candidate of candidates) {
    if (await candidate.isVisible().catch(() => false)) return candidate;
  }
  return null;
}

async function waitForVideoPromptTextbox(page, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let generateTabActivated = false;
  while (Date.now() < deadline) {
    const textbox = await visibleVideoPromptTextbox(page);
    if (textbox) return textbox;
    if (!generateTabActivated) {
      const generateTab = page.getByRole('tab', { name: /^(generate|gerar)$/i }).last();
      if (await generateTab.isVisible().catch(() => false)) {
        const selected = await generateTab.getAttribute('aria-selected').catch(() => null);
        if (selected !== 'true') await generateTab.click().catch(() => {});
        generateTabActivated = true;
      }
    }
    await page.waitForTimeout(500);
  }
  return null;
}

async function savePageDiagnostic(page, workDir, prefix) {
  // Captura o estado textual da página (título, URL e texto do body) além do
  // screenshot, para que falhas de automação sejam auto-explicativas sem
  // depender de análise visual do PNG.
  const timestamp = Date.now();
  const diagnostic = { url: page.url(), title: '', bodyText: '', bodyHtml: '' };
  try {
    diagnostic.title = await page.title().catch(() => '');
  } catch { /* ignore */ }
  try {
    diagnostic.bodyText = await page.evaluate(() => document.body?.innerText || '').catch(() => '');
  } catch { /* ignore */ }
  try {
    diagnostic.bodyHtml = await page.evaluate(() => document.body?.innerHTML || '').catch(() => '');
  } catch { /* ignore */ }

  const textPath = path.resolve(workDir, `${prefix}-${timestamp}.txt`);
  const htmlPath = path.resolve(workDir, `${prefix}-${timestamp}.html`);
  const screenshotPath = path.resolve(workDir, `${prefix}-${timestamp}.png`);

  const textSummary = [
    `URL: ${diagnostic.url}`,
    `TITLE: ${diagnostic.title}`,
    '',
    '--- BODY TEXT ---',
    diagnostic.bodyText,
  ].join('\n');
  await fs.writeFile(textPath, textSummary).catch(() => {});
  await fs.writeFile(htmlPath, diagnostic.bodyHtml).catch(() => {});
  const screenshotSaved = await page.screenshot({ path: screenshotPath, fullPage: true })
    .then(() => true)
    .catch(() => false);

  return {
    textPath,
    htmlPath,
    screenshotPath: screenshotSaved ? screenshotPath : '',
    title: diagnostic.title,
    bodyText: diagnostic.bodyText,
  };
}

async function openMostRecentProject(page) {
  // A UI atual do Vibes cria o projeto na galeria sem navegar para o editor.
  // O card do projeto recém-criado é o primeiro item clicável da galeria.
  const card = page.locator('[data-analytics-id="project_thumbnail_click"]').first();
  if (!(await card.isVisible().catch(() => false))) return false;
  await card.click().catch(() => {});
  await page.waitForURL(/\/projects\//, { timeout: 30000 }).catch(() => {});
  await settlePage(page);
  return /\/projects\//.test(new URL(page.url()).pathname);
}

async function openVideoEditor(page, workDir) {
  let textbox = await waitForVideoPromptTextbox(page, 3000);
  if (!textbox && !/\/projects\//.test(new URL(page.url()).pathname)) {
    const create = page.getByRole('button', { name: /^(create new|criar novo)$/i }).last();
    await create.waitFor({ state: 'visible', timeout: 30000 });
    await create.click();
    await page.waitForURL(/\/projects\//, { timeout: 30000 }).catch(() => {});
    await settlePage(page);
  }
  if (!textbox) textbox = await waitForVideoPromptTextbox(page, 45000);
  if (textbox) return textbox;

  // A UI atual cria o projeto na galeria sem abrir o editor. Se ainda estamos
  // na lista de projetos, clica no card do projeto recém-criado para abri-lo.
  if (!/\/projects\//.test(new URL(page.url()).pathname)) {
    const opened = await openMostRecentProject(page);
    if (opened) {
      textbox = await waitForVideoPromptTextbox(page, 30000);
      if (textbox) return textbox;
    }
  }

  // O editor é hidratado no cliente e ocasionalmente fica preso em uma tela parcial.
  // Uma recarga do projeto recém-criado recupera esse estado sem duplicar a submissão.
  await page.reload({ waitUntil: 'domcontentloaded' });
  await settlePage(page);
  await ensureAuthorized(page, { autoLogin: true });
  textbox = await waitForVideoPromptTextbox(page, 30000);
  if (textbox) return textbox;

  const diagnostic = await savePageDiagnostic(page, workDir, 'editor-timeout');
  const bodyPreview = (diagnostic.bodyText || '').replace(/\s+/g, ' ').trim().slice(0, 300);
  const detail = [
    `O editor de vídeo do Vibes não ficou disponível em ${page.url()}.`,
    diagnostic.screenshotPath ? `Diagnóstico: ${diagnostic.screenshotPath}` : '',
    diagnostic.textPath ? `Texto da página: ${diagnostic.textPath}` : '',
    bodyPreview ? `Conteúdo: ${bodyPreview}` : '',
  ].filter(Boolean).join(' ');
  throw new Error(detail);
}

async function stableImageSources(page, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  let previousKey = '';
  let stableReads = 0;
  let sources = [];
  while (Date.now() < deadline) {
    try {
      sources = await page.locator('img').evaluateAll(images => images
        .map(img => img.currentSrc || img.src)
        .filter(Boolean));
      const key = [...new Set(sources)].sort().join('\n');
      stableReads = key === previousKey ? stableReads + 1 : 0;
      previousKey = key;
      if (stableReads >= 2) return [...new Set(sources)];
    } catch {
      stableReads = 0;
    }
    await page.waitForTimeout(1000);
  }
  return [...new Set(sources)];
}

// Marcadores de recusa da Meta AI (resposta textual em vez de imagem). Cobrem
// variações em PT-BR e EN, incluindo a oferta de "versão segura" observada na
// prática: a Meta propõe remover o traço canônico em vez de gerar a imagem.
const META_REFUSAL_MARKERS = [
  'não consegui gerar',
  'nao consegui gerar',
  'não posso criar',
  'nao posso criar',
  'não posso gerar',
  'nao posso gerar',
  'não posso ajudar',
  'não posso criar uma imagem',
  'não é possível gerar',
  'nao e possivel gerar',
  'não posso concluir esse pedido',
  'não posso atender',
  'política',
  'politica da comunidade',
  'versão segura',
  'versao segura',
  'i couldn\'t generate',
  'i can\'t create',
  'i can\'t generate',
  'i can\'t help with',
  'unable to generate',
  'safer version',
  'safe version',
];

function findMetaRefusal(text) {
  const normalized = String(text || '')
    .replace(/\s+/g, ' ')
    .toLowerCase();
  if (!normalized) return null;
  const marker = META_REFUSAL_MARKERS.find(item => normalized.includes(item));
  return marker ? { marker } : null;
}

async function conversationRefusal(page, watch) {
  // Só texto NOVO depois do envio do prompt conta: a conversa é compartilhada
  // por todo o projeto, e recusas antigas de tentativas anteriores aparecem
  // no histórico. Uma recusa detectada dentro da janela de espera desta
  // geração é necessariamente resposta ao prompt atual.
  const text = await page.evaluate(() => document.body?.innerText || '');
  if (text.length <= watch.baselineLength) return null;
  const tail = text.slice(watch.baselineLength);
  return findMetaRefusal(tail);
}

async function buildRefusalError(page, refusal, watch) {
  const tail = await page
    .evaluate(() => document.body?.innerText || '')
    .then(text => text.slice(watch.baselineLength))
    .catch(() => '');
  const diagnosticPath = path.resolve(watch.workDir, `meta-refusal-${Date.now()}.png`);
  await page.screenshot({ path: diagnosticPath, fullPage: true }).catch(() => {});
  const excerpt = tail.replace(/\s+/g, ' ').trim().slice(0, 400);
  const error = new Error(
    `A Meta AI recusou o prompt de imagem (marcador: "${refusal.marker}"). ` +
      `Resposta: ${excerpt || '(indisponível)'}. Diagnóstico: ${diagnosticPath}`
  );
  error.metaRefusal = true;
  error.diagnosticPath = diagnosticPath;
  throw error;
}

// Piso de resolução das imagens GERADAS pela Meta. As gerações finais chegam
// como 1152x2048 (9:16) / proporcional em 16:9. Renders de chat (referências
// anexadas re-renderizadas na bolha da mensagem, thumbnails) ficam bem abaixo
// (ex.: 474x710 JPG) e NUNCA devem ser aceitos como resultado da geração —
// caso real de 2026-09: o render do chat foi capturado no lugar da imagem
// gerada. Piso em ~89% da resolução final para tolerar variações do provider.
const GENERATED_MIN_DIMENSIONS = {
  portrait: { width: 1024, height: 1800 },
  landscape: { width: 1800, height: 1024 },
};

function generatedImageMeetsQuality(item, requestedAspectRatio) {
  const expectedLandscape = requestedAspectRatio === '16:9';
  const floor = expectedLandscape
    ? GENERATED_MIN_DIMENSIONS.landscape
    : GENERATED_MIN_DIMENSIONS.portrait;
  return item.width >= floor.width && item.height >= floor.height;
}

async function waitForGeneratedImage(
  page,
  previousSources,
  timeoutMs,
  aspectRatio = '9:16',
  refusalWatch = null,
  referenceMeansList = [],
) {
  const previous = new Set(previousSources);
  const deadline = Date.now() + timeoutMs;
  let lastCandidate = null;
  let stableReads = 0;
  let lastRefusal = null;
  while (Date.now() < deadline) {
    let pendingRefusal = null;
    try {
      const candidates = await page.locator('img').evaluateAll((images, config) => images
        .map(img => ({ src: img.currentSrc || img.src, width: img.naturalWidth, height: img.naturalHeight }))
        .filter(item => {
          const ratio = item.width / Math.max(item.height, 1);
          const matchingRatio = config.expectedLandscape
            ? ratio >= 1.4 && ratio <= 2.1
            : ratio >= 0.4 && ratio <= 0.8;
          return item.src && item.width >= 384 && item.height >= 384 && matchingRatio;
        }), { expectedLandscape: aspectRatio === '16:9' });
      // Camada 1: apenas imagens com resolução de geração final (piso 1024x1800
      // em 9:16) podem ser aceitas — renders de chat ficam abaixo. A antiga
      // Camada 3 por DIMENSÕES foi removida: as referências canônicas são
      // geradas a 1152x2048 — a MESMA resolução das gerações — e o filtro
      // rejeitava a geração legítima como "render de chat" até o timeout
      // (bug real de 2026-09-05, frame inicial do segmento). O descarte de
      // re-renders de anexos continua garantido pela Camada 4 abaixo (hash
      // perceptual por PIXELS, imune a re-encoding) e por outputAlreadyContains.
      const generated = candidates.filter(item => generatedImageMeetsQuality(item, aspectRatio))
        .find(item => !previous.has(item.src));
      if (generated) {
        // Exige estabilidade: a mesma imagem nova precisa persistir por duas
        // leituras consecutivas antes de ser aceita, evitando capturar um
        // placeholder ou uma imagem de geração anterior que carregou tarde.
        if (generated.src === lastCandidate) {
          stableReads += 1;
          if (stableReads >= 2) {
            // Camada 4: antes de aceitar, verifica se a candidata é um
            // re-render de uma referência enviada (mesma imagem em pixels).
            // Sem assinatura computável = sem veredito = aceita.
            const candidateMeans = await imageBlockMeans(page, generated.src);
            if (looksLikeReferenceRender(candidateMeans, referenceMeansList)) {
              lastCandidate = null;
              stableReads = 0;
            } else {
              return generated.src;
            }
          }
        } else {
          lastCandidate = generated.src;
          stableReads = 1;
        }
      } else {
        lastCandidate = null;
        stableReads = 0;
        // Recusa da Meta: resposta com TEXTO em vez de imagem. Só é avaliada
        // quando NENHUMA imagem nova está à vista (a imagem vence qualquer
        // texto) e exige o mesmo marcador em 2 leituras consecutivas.
        if (refusalWatch) {
          pendingRefusal = await conversationRefusal(page, refusalWatch).catch(() => null);
        }
      }
    } catch {
      // A Meta pode navegar durante a geração; tente novamente até o prazo expirar.
      lastCandidate = null;
      stableReads = 0;
    }
    if (pendingRefusal) {
      if (lastRefusal && lastRefusal.marker === pendingRefusal.marker) {
        throw await buildRefusalError(page, pendingRefusal, refusalWatch);
      }
      lastRefusal = pendingRefusal;
    } else {
      lastRefusal = null;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error('Meta AI não apresentou uma nova imagem vertical em alta resolução.');
}

// Detecta uma geração AINDA EM ANDAMENTO na conversa (IM-17). Somente sinais
// TRANSITÓRIOS e VISÍVEIS valem. Lições de falso positivo já aprendidas:
// - A home e a conversa da Meta mantêm um elemento [role="progressbar"] OCIOSO
//   permanente no DOM — só conta se estiver realmente visível (offsetParent e
//   rects) com tamanho útil.
// - Botões "Refazer"/"Perguntar novamente" e classes loading/pending existem
//   permanentemente no histórico — nunca usados como sinal.
// A lista de sinais ativos retorna para diagnóstico quando a espera estoura.
function metaInFlightSignals(page) {
  return page.evaluate(() => {
    const signals = [];
    const visible = element => {
      if (!element) return false;
      const style = getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none') return false;
      const rect = element.getBoundingClientRect();
      return !!(element.offsetParent || element.getClientRects().length)
        && rect.width >= 8 && rect.height >= 8;
    };
    const progress = [...document.querySelectorAll('[role="progressbar"], [aria-busy="true"]')]
      .filter(visible);
    if (progress.length) signals.push(`progressbar(${progress.length})`);
    const stopButton = [...document.querySelectorAll('button')].find(button => {
      const label = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('title') || ''}`.toLowerCase();
      return visible(button) && /interromp|parar|stop/.test(label);
    });
    if (stopButton) signals.push('stop-button');
    const tail = (document.body?.innerText || '').slice(-600);
    if (/gerando imagem|generating image/i.test(tail)) signals.push('text-gerando');
    return signals;
  });
}

// Aguarda a conversa "assentar": nenhuma geração em andamento. Chamado logo
// ANTES de preparar o novo prompt, garante que um prompt só parte quando a
// mídia da referência anterior já foi gerada. timeoutMs <= 0 desativa o gate.
// Timeout gera erro claro (com os sinais ativos) em vez de enviar um segundo
// prompt sobre a geração anterior.
async function ensureMetaSettled(page, timeoutMs, workDir) {
  if (!(timeoutMs > 0)) return;
  const deadline = Date.now() + timeoutMs;
  let signals = [];
  while (Date.now() < deadline) {
    signals = await metaInFlightSignals(page).catch(() => ['erro-de-leitura']);
    if (!signals.length) {
      // Uma única leitura limpa pode pegar um instante entre fases da UI;
      // confirma com uma segunda leitura antes de liberar o envio.
      await page.waitForTimeout(1500);
      signals = await metaInFlightSignals(page).catch(() => ['erro-de-leitura']);
      if (!signals.length) return;
    }
    await page.waitForTimeout(2000);
  }
  const diagnosticPath = workDir
    ? path.resolve(workDir, `meta-settled-${Date.now()}.png`)
    : '';
  if (diagnosticPath) await page.screenshot({ path: diagnosticPath, fullPage: true }).catch(() => {});
  throw new Error(
    'A geração anterior da Meta AI ainda não terminou; o novo prompt NÃO foi enviado. '
      + `Sinais ativos: ${signals.join(', ')}. `
      + `Espera pela conclusão esgotou ${Math.round(timeoutMs / 1000)}s.`
      + (diagnosticPath ? ` Diagnóstico: ${diagnosticPath}` : ''),
  );
}

// ===== Fechamento manual do navegador (definitivo) =====
// Se o usuário fecha a janela do navegador aberta pela automação, o fechamento
// é RESPEITADO: a geração em curso falha com erro claro e os requests
// seguintes falham rápido SEM reabrir o navegador, até uma ação explícita do
// usuário (Autorizar Meta / nova geração) limpar o estado via resume.
const USER_CLOSED_ERROR = 'user-closed-browser: o navegador foi fechado manualmente.';
const userClosedStatePath = profilePath => path.join(
  profilePath, 'Storytelling', 'user-closed-browser.flag',
);
// Contextos que a PRÓPRIA automação está fechando: o evento 'close' das
// páginas deles NÃO é fechamento manual do usuário.
const automationClosingContexts = new WeakSet();

async function loadUserClosedState(profilePath) {
  try {
    const raw = await fs.readFile(userClosedStatePath(profilePath), 'utf8');
    const parsed = JSON.parse(raw);
    if (parsed && parsed.userClosed === true) {
      return { userClosed: true, closedAt: String(parsed.closedAt || '') };
    }
  } catch { /* ausente = não fechado */ }
  return { userClosed: false, closedAt: '' };
}

async function saveUserClosedState(profilePath, closedAt) {
  await fs.mkdir(path.dirname(userClosedStatePath(profilePath)), { recursive: true });
  await fs.writeFile(
    userClosedStatePath(profilePath),
    JSON.stringify({ userClosed: true, closedAt: closedAt || new Date().toISOString() }),
  );
}

async function clearUserClosedState(profilePath) {
  await fs.rm(userClosedStatePath(profilePath), { force: true }).catch(() => {});
}

// Observa o fechamento da janela principal e marca o estado imediatamente.
// Ignora fechamentos feitos pela própria automação (closePersistentSession).
function watchUserBrowserClose(context, profilePath) {
  let closed = false;
  const pages = context.pages();
  if (!pages.length) return () => {};
  const markClosed = () => {
    if (closed || automationClosingContexts.has(context)) return;
    closed = true;
    void saveUserClosedState(profilePath);
  };
  for (const page of pages) {
    page.once('close', markClosed);
  }
  return () => {
    for (const page of pages) {
      page.off('close', markClosed);
    }
  };
}

// Para generate-image/submit-video: falha rápido se o usuário já fechou o
// navegador, sem abrir nenhum novo. Erro com o marcador user-closed-browser.
async function rejectIfUserClosed(profilePath) {
  const state = await loadUserClosedState(profilePath);
  if (state.userClosed) {
    throw new Error(
      `${USER_CLOSED_ERROR} Fechado em ${state.closedAt || 'data desconhecida'}. `
        + 'Use “Autorizar Meta” nos Ajustes ou dispare uma nova geração para retomar.',
    );
  }
}

// Fluxo authorize: se o usuário FECHOU o navegador antes, este clique limpa o
// estado definitivo; caso contrário, apenas limpa um flag eventualmente velho.
async function authorizeAfterUserClose(payload) {
  await clearUserClosedState(payload.profilePath);
  return authorize(payload);
}

async function outputAlreadyContains(outputDir, bytes) {
  const wantedHash = crypto.createHash('sha256').update(bytes).digest('hex');
  const entries = await fs.readdir(outputDir, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const existing = await fs.readFile(path.join(outputDir, entry.name)).catch(() => null);
    if (!existing) continue;
    const existingHash = crypto.createHash('sha256').update(existing).digest('hex');
    if (existingHash === wantedHash) return true;
  }
  return false;
}

function conversationStatePath(profilePath, conversationKey) {
  const key = crypto.createHash('sha256').update(String(conversationKey || 'default')).digest('hex');
  return path.join(profilePath, 'Storytelling', 'meta-conversations', `${key}.json`);
}

function reusableConversationUrl(value) {
  try {
    const url = new URL(String(value || ''));
    return url.protocol === 'https:'
      && ['meta.ai', 'www.meta.ai'].includes(url.hostname)
      && url.pathname !== '/'
      && url.pathname !== '/ai-image-generator/';
  } catch {
    return false;
  }
}

async function loadConversationUrl(profilePath, conversationKey) {
  const statePath = conversationStatePath(profilePath, conversationKey);
  const state = await fs.readFile(statePath, 'utf8').then(JSON.parse).catch(() => ({}));
  return reusableConversationUrl(state.url) ? state.url : IMAGE_URL;
}

async function saveConversationUrl(profilePath, conversationKey, url) {
  if (!reusableConversationUrl(url)) return;
  const statePath = conversationStatePath(profilePath, conversationKey);
  await fs.mkdir(path.dirname(statePath), { recursive: true });
  await fs.writeFile(statePath, JSON.stringify({ url, updatedAt: new Date().toISOString() }));
}

async function authorize(payload) {
  const destination = payload.destination === 'vibes' ? VIBES_URL : META_HOME_URL;
  const { context, page } = await persistentPage(payload.profilePath, false);
  await page.goto(destination, { waitUntil: 'domcontentloaded' });
  const deadline = Date.now() + 9 * 60 * 1000;
  while (Date.now() < deadline) {
    if (page.isClosed()) {
      await releasePersistentPage(context);
      return { authorized: true };
    }
    if (!(await loginRequired(page))) {
      await page.waitForTimeout(1500);
      await releasePersistentPage(context);
      return { authorized: true };
    }
    await page.waitForTimeout(1000);
  }
  await releasePersistentPage(context);
  throw new Error('Tempo de autorização Meta esgotado.');
}

async function uploadLocalReferences(page, references) {
  const files = references.filter(value => typeof value === 'string' && !value.startsWith('data:'));
  if (!files.length) return;
  const existing = [];
  for (const file of files) {
    try { await fs.access(file); existing.push(file); } catch { /* ignore unavailable history */ }
  }
  if (!existing.length) return;
  const input = page.locator('input[type=file]').first();
  if (!(await input.count())) {
    await page.getByRole('button', { name: /adicionar anexo|add attachment|upload/i }).first().click();
  }
  await page.locator('input[type=file]').first().setInputFiles(existing.slice(0, 4));
}

async function mediaBytes(page, src) {
  if (/^https?:/i.test(src)) {
    const response = await page.context().request.get(src);
    if (!response.ok()) throw new Error(`Download Meta falhou com HTTP ${response.status()}`);
    return { bytes: await response.body(), contentType: response.headers()['content-type'] || '' };
  }
  const result = await page.evaluate(async mediaUrl => {
    const response = await fetch(mediaUrl);
    const bytes = new Uint8Array(await response.arrayBuffer());
    let binary = '';
    const block = 0x8000;
    for (let index = 0; index < bytes.length; index += block) {
      binary += String.fromCharCode(...bytes.subarray(index, index + block));
    }
    return { base64: btoa(binary), contentType: response.headers.get('content-type') || '' };
  }, src);
  return { bytes: Buffer.from(result.base64, 'base64'), contentType: result.contentType };
}

async function withDeadline(promise, budgetMs, message) {
  // Aplica um prazo a uma promessa sem abortar a operação subjacente:
  // rejeita com mensagem clara se o orçamento estourar (a falha rápida
  // reinicia o bridge no próximo request, espelhando o timeout do Python).
  let timer = null;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(message)), budgetMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// Camada 4 (cinturão contra re-encoding, substitui a Camada 3 por dimensões):
// compara os PIXELS da candidata com os das referências enviadas. A imagem é
// reduzida a uma grade 16x16 (canvas) e conta-se quantas células mudaram mais
// de 50 em algum canal RGB. Um re-render do anexo no chat é a MESMA imagem —
// quase nenhuma célula muda (calibração 2026-09-05 com gerações reais: 0-4).
// Uma geração nova, mesmo fortemente guiada pelas referências, muda ≥23
// células. A antiga Camada 3 comparava DIMENSÕES — mas as referências
// canônicas são 1152x2048, a mesma resolução das gerações, e terminava
// rejeitando a geração legítima (bug real de 2026-09-05, frame inicial).
const REFERENCE_RENDER_GRID = 16;
const REFERENCE_RENDER_CELL_DELTA = 50;
const REFERENCE_RENDER_MAX_HOT_CELLS = 5;

async function imageBlockMeans(page, src) {
  return page.evaluate(async ([imageSrc, size]) => {
    const load = value => new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error('image-load-failed'));
      image.src = value;
    });
    const means = image => {
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext('2d');
      if (!context) return null;
      context.drawImage(image, 0, 0, size, size);
      const { data } = context.getImageData(0, 0, size, size);
      const result = [];
      for (let index = 0; index < size * size; index += 1) {
        const offset = index * 4;
        result.push(data[offset], data[offset + 1], data[offset + 2]);
      }
      return result;
    };
    try {
      return means(await load(imageSrc));
    } catch {
      // Canvas contaminado (imagem de outra origem sem CORS): tenta baixar os
      // bytes via fetch (respeitando CORS) e recarregar via data: URL, que
      // não contamina o canvas. Sem veredito se ambos falharem.
      try {
        const response = await fetch(imageSrc, { mode: 'cors' });
        const blob = await response.blob();
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(new Error('blob-read-failed'));
          reader.readAsDataURL(blob);
        });
        return means(await load(dataUrl));
      } catch {
        return null;
      }
    }
  }, [src, REFERENCE_RENDER_GRID]);
}

// Número de células da grade cuja maior diferença de canal excede o limiar.
// Sem veredito (candidata nula ou grades de tamanhos distintos) = Infinity.
function referenceRenderHotCells(candidateMeans, referenceMeans) {
  if (!candidateMeans || !referenceMeans) return Infinity;
  if (candidateMeans.length !== referenceMeans.length) return Infinity;
  let hot = 0;
  for (let index = 0; index < candidateMeans.length; index += 3) {
    const delta = Math.max(
      Math.abs(candidateMeans[index] - referenceMeans[index]),
      Math.abs(candidateMeans[index + 1] - referenceMeans[index + 1]),
      Math.abs(candidateMeans[index + 2] - referenceMeans[index + 2]),
    );
    if (delta > REFERENCE_RENDER_CELL_DELTA) hot += 1;
  }
  return hot;
}

function looksLikeReferenceRender(candidateMeans, referenceMeansList) {
  if (!candidateMeans || !referenceMeansList.length) return false;
  return referenceMeansList.some(
    referenceMeans => referenceRenderHotCells(candidateMeans, referenceMeans)
      <= REFERENCE_RENDER_MAX_HOT_CELLS,
  );
}

async function referenceBlockMeansList(page, references) {
  const files = (references || []).filter(
    value => typeof value === 'string' && !value.startsWith('data:'),
  );
  const meansList = [];
  for (const file of files) {
    // Lê os bytes em Node e passa como data: URL — página https não carrega
    // file:/// (bloqueado), e data: URL não contamina o canvas.
    try {
      const bytes = await fs.readFile(file);
      const extension = path.extname(file).toLowerCase().replace('.', '') || 'png';
      const mime = extension === 'jpg' || extension === 'jpeg'
        ? 'image/jpeg'
        : extension === 'webp' ? 'image/webp' : 'image/png';
      const means = await imageBlockMeans(page, `data:${mime};base64,${bytes.toString('base64')}`);
      if (means) meansList.push(means);
    } catch {
      // Arquivo ilegível: referência sem assinatura, filtro ignora.
    }
  }
  return meansList;
}

async function generateImage(payload) {
  // Fechamento manual do navegador é definitivo: se o usuário já fechou,
  // falha rápido SEM reabrir navegador (o retry do job não reabre nada).
  await rejectIfUserClosed(payload.profilePath);
  const { context, page } = await persistentPage(payload.profilePath, false);
  // Observa o fechamento manual da janela para marcar o estado definitivo.
  const stopUserCloseWatch = watchUserBrowserClose(context, payload.profilePath);
  // Orçamento próprio para navegação+autenticação+upload (INC-06): o Python
  // dá ao bridge timeout_seconds = timeoutSeconds + 60; sem um prazo para a
  // fase de preparação, uma navegação lenta consumiria a margem inteira e a
  // geração em si abortaria do lado Python com o browser ainda gerando.
  // A fase de preparação recebe no máximo metade da margem (30s por padrão);
  // o relógio de geração continua medindo APENAS a espera pela imagem.
  const prepBudgetMs = Math.max(15000, Math.min(60000, 30000));
  try {
    // Reutiliza a conversa persistente do projeto para manter todas as
    // referências visuais no mesmo chat. O lazy-load de imagens de gerações
    // anteriores é mitigado pelo descarte de duplicados abaixo.
    const conversationUrl = await loadConversationUrl(
      payload.profilePath,
      payload.conversationKey,
    );
    await withDeadline(
      page.goto(conversationUrl, {
        waitUntil: 'domcontentloaded',
        // Timeout explícito: o default da página (15s) derrubava a navegação
        // no meio do caminho em redes oscilantes, antes do orçamento de
        // preparação (30s) ser sequer consultado.
        timeout: prepBudgetMs,
      }),
      prepBudgetMs,
      'A navegação para a conversa do Meta AI demorou demais (orçamento de preparação).',
    );
    await withDeadline(settlePage(page), prepBudgetMs, 'A estabilização da página demorou demais.');
    await withDeadline(ensureAuthorized(page), prepBudgetMs, 'A autorização do Meta AI demorou demais.');
    await withDeadline(
      uploadLocalReferences(page, payload.references || []),
      prepBudgetMs,
      'O upload das referências demorou demais (orçamento de preparação).',
    );
    // Captura as fontes DEPOIS do upload das referências: as imagens anexadas
    // entram no conjunto "anterior" e não são confundidas com a imagem gerada.
    const oldSources = await stableImageSources(page);
    await fs.mkdir(payload.outputDir, { recursive: true });
    // Gate de conclusão (IM-17): antes de preparar/enviar o novo prompt,
    // garante que a geração anterior já terminou. Sem isso, uma nova
    // tentativa (retry ou lote) envia um segundo prompt com a Meta AI ainda
    // gerando o anterior — ela então mistura as duas gerações no chat.
    const settledWaitMs = Math.max(
      0,
      Number(payload.settledWaitSeconds === undefined ? 240 : payload.settledWaitSeconds) * 1000,
    );
    await ensureMetaSettled(page, settledWaitMs, payload.outputDir);
    // Linha de base do texto da conversa para a detecção de recusa: somente
    // texto NOVO, surgido depois do envio do prompt, pode ser resposta da Meta
    // a ESTA geração (a conversa é compartilhada por todo o projeto).
    const baselineText = await page.evaluate(() => document.body?.innerText || '').catch(() => '');
    const refusalWatch = { baselineLength: baselineText.length, workDir: payload.outputDir };
    let textbox = page.getByRole('textbox', { name: /pergunte à meta ai|ask meta ai/i }).first();
    if (!(await textbox.isVisible().catch(() => false))) {
      textbox = page.locator('textarea, [contenteditable="true"], input[type="text"]').last();
    }
    await textbox.waitFor({ state: 'visible', timeout: 20000 });
    const aspectRatio = payload.aspectRatio === '16:9' ? '16:9' : '9:16';
    const composition = aspectRatio === '16:9'
      ? 'Composição horizontal cinematográfica 16:9, alta resolução.'
      : 'Composição vertical 9:16, alta resolução.';
    const generationPrompt = `${payload.prompt} ${composition}`;
    await textbox.fill(generationPrompt);
    const sendButton = page.getByRole('button', { name: /enviar|send/i }).first();
    if (await sendButton.isVisible().catch(() => false)) {
      await sendButton.click({ timeout: 20000 });
    } else {
      await textbox.press('Enter');
    }
    await page.waitForTimeout(2000);
    await saveConversationUrl(payload.profilePath, payload.conversationKey, page.url());
    // O deadline de geração usa timeoutSeconds + uma fração da espera de
    // assentamento: o gate IM-17 (ensureMetaSettled) roda ANTES do envio e
    // não consome este prazo, mas a Meta pode demorar MINUTOS para gerar —
    // desistir em 180s com a imagem completa na tela (bug real de 2026-09-06:
    // frame do Sorveteiro visível no screenshot do timeout) desperdiça a
    // geração. O Python externo já dá timeoutSeconds + settled + 60; o interno
    // ganha a mesma margem de settled + 60s para a espera pela imagem.
    const settledWaitSeconds = Math.max(
      0,
      Number(payload.settledWaitSeconds === undefined ? 240 : payload.settledWaitSeconds),
    );
    const generationTimeoutMs = Math.max(
      30000,
      (Number(payload.timeoutSeconds || 180) + settledWaitSeconds + 60) * 1000,
    );
    // Aguarda a imagem realmente nova desta geração. Imagens de gerações
    // anteriores podem carregar tardiamente (lazy-load) ao reabrir a conversa e
    // aparecer como "novas"; nesse caso descartamos o duplicado e continuamos
    // esperando, em vez de falhar e deixar a geração em andamento órfã.
    // Recusas textuais da Meta interrompem a espera imediatamente (erro
    // metaRefusal propagado por waitForGeneratedImage).
    const deadline = Date.now() + generationTimeoutMs;
    const seenSources = new Set(oldSources);
    // Camada 4: assinaturas pixel (grade 16x16 de médias RGB) dos arquivos de
    // referência enviados — candidata praticamente IDÊNTICA a um anexo é
    // render de chat, não a geração. Calculadas no browser (canvas); falha de
    // leitura = referência sem assinatura = filtro ignora.
    const referenceMeansList = await referenceBlockMeansList(page, payload.references || []);
    let src = null;
    let refusalError = null;
    let inFlightWaitLogged = false;
    while (Date.now() < deadline) {
      // Janela fechada manualmente durante a espera: interrompe AGORA com o
      // erro tipado em vez de girar até o timeout tentando ler a página morta.
      if (page.isClosed()) {
        throw new Error(
          `${USER_CLOSED_ERROR} A janela foi fechada durante a geração.`,
        );
      }
      // Camada 2: só baixa quando a geração da Meta CONCLUUIU (nenhum sinal
      // em voo). A Meta evolui a imagem em estágios (rascunho → final) e o
      // download antecipado entregava rascunhos/renders de chat.
      while (Date.now() < deadline) {
        const signals = await metaInFlightSignals(page).catch(() => ['erro-de-leitura']);
        if (!signals.length) break;
        if (!inFlightWaitLogged) {
          console.log(
            `[bridge] generate-image: aguardando conclusão da geração (sinais: ${signals.join(', ')})`,
          );
          inFlightWaitLogged = true;
        }
        await page.waitForTimeout(2000);
      }
      const candidate = await waitForGeneratedImage(
        page,
        [...seenSources],
        Math.max(5000, deadline - Date.now()),
        aspectRatio,
        refusalWatch,
        referenceMeansList,
      ).catch(error => {
        if (error && error.metaRefusal) refusalError = error;
        return null;
      });
      if (refusalError) break;
      if (!candidate) break;
      const downloaded = await mediaBytes(page, candidate).catch(() => null);
      if (!downloaded) {
        seenSources.add(candidate);
        continue;
      }
      if (await outputAlreadyContains(payload.outputDir, downloaded.bytes)) {
        // Duplicado: imagem de uma geração anterior. Descarta e continua.
        seenSources.add(candidate);
        continue;
      }
      src = { candidate, downloaded };
      break;
    }
    if (refusalError) {
      throw refusalError;
    }
    if (!src) {
      const diagnosticPath = path.resolve(payload.outputDir, `meta-timeout-${Date.now()}.png`);
      await page.screenshot({ path: diagnosticPath, fullPage: true }).catch(() => {});
      throw new Error(`Meta AI não apresentou uma nova imagem vertical em alta resolução. Diagnóstico: ${diagnosticPath}`);
    }
    await saveConversationUrl(payload.profilePath, payload.conversationKey, page.url());
    const contentType = src.downloaded.contentType.split(';')[0] || 'image/png';
    const extension = contentType.includes('jpeg') ? '.jpg' : contentType.includes('webp') ? '.webp' : '.png';
    const jobId = crypto.randomUUID();
    const filePath = path.resolve(payload.outputDir, `meta-${jobId}${extension}`);
    await fs.writeFile(filePath, src.downloaded.bytes);
    return { filePath, contentType, jobId, conversationUrl: page.url() };
  } finally {
    stopUserCloseWatch();
    // Fecha o navegador de imediato (sucesso ou falha). O ciclo completo por
    // referência é: abre → envia prompt → espera a geração → entrega a imagem
    // → fecha. A conversa persistida do projeto garante que a próxima
    // referência continue no MESMO chat.
    await closePersistentSession(context);
  }
}

async function writeDataUrl(value, destination) {
  const match = /^data:([^;,]+)?(?:;base64)?,(.*)$/s.exec(value || '');
  if (!match) return null;
  const bytes = value.includes(';base64,')
    ? Buffer.from(match[2], 'base64')
    : Buffer.from(decodeURIComponent(match[2]), 'utf8');
  await fs.writeFile(destination, bytes);
  return destination;
}

// Detecta o formato real pelos bytes (o data-URL pode mentir: frames da Meta
// chegam como data:image/webp mesmo quando salvos com extensão .png, e o
// Vibes rejeita a mídia cuja extensão não casa com os bytes — "Falha ao
// carregar").
function imageExtensionFromSignature(buffer) {
  if (buffer.length >= 12 && buffer.toString('ascii', 0, 4) === 'RIFF' && buffer.toString('ascii', 8, 12) === 'WEBP') {
    return '.webp';
  }
  if (buffer.length >= 3 && buffer[0] === 0x89 && buffer.toString('ascii', 1, 4) === 'PNG') {
    return '.png';
  }
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) {
    return '.jpg';
  }
  if (buffer.length >= 6 && buffer.toString('ascii', 0, 3) === 'GIF') {
    return '.gif';
  }
  return null;
}

async function uploadVideoInputs(page, payload, workDir) {
  const entries = [];
  for (const [kind, source] of [
    ['start', payload.first_frame],
    ['end', payload.final_frame],
  ]) {
    if (!source) continue;
    let file = source;
    if (source.startsWith('data:')) {
      // Escreve com a extensão REAL dos bytes (não sempre .png): o Vibes
      // valida extensão × conteúdo no upload e rejeita a combinação errada.
      const match = /^data:([^;,]+)?(?:;base64)?,(.*)$/s.exec(source);
      const bytes = match
        ? (source.includes(';base64,') ? Buffer.from(match[2], 'base64') : Buffer.from(decodeURIComponent(match[2]), 'utf8'))
        : Buffer.alloc(0);
      const extension = imageExtensionFromSignature(bytes) || '.png';
      file = path.join(workDir, `${kind}-frame${extension}`);
      if (!(await writeDataUrl(source, file))) continue;
    } else {
      try { await fs.access(source); } catch { continue; }
    }
    entries.push({ kind, file });
  }
  if (!entries.length) return;
  // O filechooser nativo do Vibes é entregue como evento da página. O handler
  // global (preenchido por uploadFrameIntoDialog antes do clique) responde com
  // o arquivo do frame desta iteração.
  page.on('filechooser', chooser => {
    if (typeof pendingFileChooserResolve === 'function') {
      const resolve = pendingFileChooserResolve;
      pendingFileChooserResolve = null;
      resolve(chooser);
    } else {
      chooser.setFiles([]).catch(() => {});
    }
  });
  await page.getByRole('button', {
    name: /start, end frame|frame inicial.*final|quadro inicial.*final/i,
  }).click();
  for (const entry of entries) {
    const addName = entry.kind === 'start'
      ? /add start frame|adicionar (?:frame|quadro) inicial/i
      : /add end frame|adicionar (?:frame|quadro) final/i;
    await page.getByRole('button', { name: addName }).first().click();
    await page.waitForTimeout(2000);
    // A UI atual abre o diálogo "Selecionar quadro inicial/final" imediatamente.
    const selectionName = entry.kind === 'start'
      ? /selecionar (?:frame|quadro) inicial/i
      : /selecionar (?:frame|quadro) final/i;
    const selectionHeading = page
      .getByRole('heading', { name: selectionName })
      .first()
      .or(page.locator(`h3:text-is("${entry.kind === 'start' ? 'Selecionar quadro inicial' : 'Selecionar quadro final'}")`).first());
    await selectionHeading.waitFor({ state: 'visible', timeout: 30000 });
    const selectionDialog = selectionHeading.locator('xpath=ancestor::*[@role="dialog"]').first();
    const dialog = (await selectionDialog.count()) ? selectionDialog : page.getByRole('dialog').last();
    try {
      await uploadFrameIntoDialog(page, dialog, entry.file);
    } catch (error) {
      // Captura o HTML do dialog para diagnosticar mudanças de UI no upload.
      const diagnostic = await savePageDiagnostic(page, workDir, 'upload-error');
      const detail = [
        `Falha ao enviar o frame ${entry.kind} do Vibes.`,
        error instanceof Error ? error.message : String(error),
        diagnostic.textPath ? `Texto da página: ${diagnostic.textPath}` : '',
      ].filter(Boolean).join(' ');
      throw new Error(detail);
    }
  }
}

async function uploadFrameIntoDialog(page, dialog, file) {
  // Fluxo da UI atual do Vibes (verificado por sondagem em set/2026):
  // "Selecionar quadro inicial/final" → botão "Carregar" abre um SEGUNDO
  // diálogo ("Carregar imagens") com a área clicável "Click to add or drag
  // and drop media"; clicar nela dispara o filechooser nativo. Após o upload,
  // o botão azul "Carregar" do diálogo de upload confirma ("Mídia carregada"),
  // volta ao diálogo de seleção, e a miniatura demora alguns segundos para
  // aparecer na grade "Este projeto".
  // O diálogo é montado de forma progressiva pelo site: logo após abrir, a
  // página pode estar em hidratação parcial (observado em produção em 08/09/2026:
  // o dump do erro mostrou o diálogo SEM o botão "Carregar" e a página sem
  // "Upload media"; sondagem ao vivo minutos depois mostrou ambos presentes).
  // Por isso o botão é REPESQUISADO em loop — locator é lazy, cada iteração
  // resolve contra o DOM atual — em vez de um único teste de visibilidade.
  const loadButtonDeadline = Date.now() + 20000;
  let loadButtonVisible = false;
  while (Date.now() < loadButtonDeadline) {
    loadButtonVisible = await dialog
      .getByRole('button', { name: /carregar/i })
      .first()
      .isVisible()
      .catch(() => false);
    if (loadButtonVisible) break;
    await page.waitForTimeout(1000);
  }
  if (!loadButtonVisible) {
    throw new Error('Botão "Carregar" não encontrado no diálogo de seleção do Vibes.');
  }
  await dialog.getByRole('button', { name: /carregar/i }).first().click();
  await page.waitForTimeout(2000);

  // Diálogo "Carregar imagens"
  let uploadDialog = null;
  const dialogDeadline = Date.now() + 15000;
  while (Date.now() < dialogDeadline) {
    const dialogs = page.getByRole('dialog');
    const count = await dialogs.count().catch(() => 0);
    for (let index = count - 1; index >= 0; index -= 1) {
      const candidate = dialogs.nth(index);
      if (!(await candidate.isVisible().catch(() => false))) continue;
      const text = (await candidate.innerText().catch(() => '')).slice(0, 400);
      if (/carregar imagens|upload images/i.test(text)) {
        uploadDialog = candidate;
        break;
      }
    }
    if (uploadDialog) break;
    await page.waitForTimeout(1000);
  }
  if (!uploadDialog) {
    throw new Error('Diálogo "Carregar imagens" do Vibes não ficou disponível.');
  }

  // Área clicável que dispara o filechooser nativo. O handler registrado em
  // uploadVideoInputs responde com o arquivo do frame desta iteração.
  pendingFileChooserResolve = null;
  const chooserPromise = new Promise(resolve => {
    pendingFileChooserResolve = resolve;
  });
  const dropArea = uploadDialog
    .getByText(/click to add|arraste e solte|drag and drop/i)
    .first();
  if (await dropArea.isVisible().catch(() => false)) {
    await dropArea.click();
  } else {
    // Fallback: qualquer elemento clicável de upload dentro do diálogo.
    await uploadDialog.locator('body').click({ position: { x: 230, y: 200 } }).catch(() => {});
  }
  const chooser = await Promise.race([
    chooserPromise,
    new Promise(resolve => setTimeout(() => resolve(null), 10000)),
  ]);
  if (chooser) {
    await chooser.setFiles(file).catch(error => {
      throw new Error(`Falha ao definir o arquivo no filechooser do Vibes: ${error.message}`);
    });
  } else {
    throw new Error('O Vibes não abriu o seletor de arquivos ao clicar na área de upload.');
  }
  await page.waitForTimeout(5000);

  // Confirma o upload com o botão azul "Carregar" do diálogo de upload.
  const confirmUpload = uploadDialog.getByRole('button', { name: /^carregar$/i }).last();
  if (await confirmUpload.isVisible().catch(() => false)) {
    await confirmUpload.click().catch(() => {});
  }

  // Volta ao diálogo de seleção e aguarda a miniatura aparecer na grade.
  const selectionHeading = dialog.getByRole('heading', {
    name: /selecionar (?:frame|quadro) (?:inicial|final)/i,
  }).first();
  const heading = selectionHeading.or(
    page.getByRole('heading', { name: /selecionar (?:frame|quadro) (?:inicial|final)/i }).first(),
  );
  await heading.waitFor({ state: 'visible', timeout: 30000 }).catch(() => {});
  const selectionDialog = heading.locator('xpath=ancestor::*[@role="dialog"]').first();
  const candidates = (await selectionDialog.count() ? selectionDialog : dialog).locator('img');
  // A miniatura pode levar ~10s para aparecer ("Mídia carregada" → grade).
  const thumbDeadline = Date.now() + 30000;
  let thumbSeen = false;
  while (Date.now() < thumbDeadline) {
    if ((await candidates.count().catch(() => 0)) > 0) {
      thumbSeen = true;
      break;
    }
    await page.waitForTimeout(1500);
  }
  if (!thumbSeen) {
    throw new Error('A miniatura do frame enviado não apareceu na grade do Vibes.');
  }
  await candidates.last().click();
  const add = (await selectionDialog.count() ? selectionDialog : dialog).getByRole('button', {
    name: /add to video|adicionar ao v.deo/i,
  }).last();
  await add.waitFor({ state: 'visible', timeout: 30000 });
  await add.click();
  await heading.waitFor({ state: 'hidden', timeout: 30000 }).catch(() => {});
}

async function configureVideoDuration(page, durationSeconds) {
  const duration = Math.max(1, Number(durationSeconds || 10));
  const durationControl = page.getByRole('button', {
    name: /duration|duração|seconds|segundos/i,
  }).last();
  if (await durationControl.isVisible().catch(() => false)) {
    await durationControl.click().catch(() => {});
  }
  const exactDuration = new RegExp(`^${duration}\\s*(?:s|sec|secs|second|seconds|segundo|segundos)$`, 'i');
  const option = page.getByText(exactDuration).last();
  if (await option.isVisible().catch(() => false)) {
    await option.click();
    return true;
  }
  return false;
}

async function videoSources(page) {
  const collected = [];
  const readSources = async () => page.locator('video, video source').evaluateAll(elements => elements
    .map(element => element.currentSrc || element.src).filter(Boolean));
  // Result cards may be virtualized. Reading after incremental scrolling gives each
  // card a chance to attach its video element without requiring all four at once.
  for (const ratio of [0, 0.35, 0.7, 1]) {
    try {
      await page.evaluate(value => window.scrollTo(0, document.body.scrollHeight * value), ratio);
      await page.waitForTimeout(500);
      collected.push(...await readSources());
    } catch {
      // Vibes may replace the document while results are being attached. The next
      // poll reopens the persisted project and continues from the checkpoint.
    }
  }
  // O Vibes pode manter a quarta opção em um carrossel horizontal virtualizado.
  // Percorra todos os contêineres roláveis e leia novamente os elementos anexados.
  try {
    const horizontalContainers = page.locator('*').filter({
      has: page.locator('video, video source'),
    });
    const count = Math.min(await horizontalContainers.count(), 20);
    for (let index = 0; index < count; index += 1) {
      const container = horizontalContainers.nth(index);
      const scrollable = await container.evaluate(element => (
        element.scrollWidth > element.clientWidth + 40
      )).catch(() => false);
      if (!scrollable) continue;
      for (const ratio of [0, 0.5, 1]) {
        await container.evaluate((element, value) => {
          element.scrollLeft = (element.scrollWidth - element.clientWidth) * value;
        }, ratio).catch(() => {});
        await page.waitForTimeout(400);
        collected.push(...await readSources().catch(() => []));
      }
    }
  } catch {
    // Uma troca de contexto será recuperada no próximo polling.
  }
  return [...new Set(collected)];
}

function videoStatePath(workDir) {
  return path.resolve(workDir, 'job-state.json');
}

async function saveVideoState(statePath, state) {
  state.updatedAt = new Date().toISOString();
  await fs.writeFile(statePath, JSON.stringify(state, null, 2));
}

async function loadVideoState(statePath) {
  const state = JSON.parse(await fs.readFile(statePath, 'utf8'));
  if (!state || typeof state !== 'object' || !state.jobId || !state.projectUrl) {
    throw new Error('Checkpoint de geração do Vibes inválido.');
  }
  const project = new URL(String(state.projectUrl));
  if (project.protocol !== 'https:' || !['vibes.ai', 'www.vibes.ai'].includes(project.hostname)) {
    throw new Error('Checkpoint aponta para um projeto Vibes inválido.');
  }
  if (path.resolve(state.workDir) !== path.dirname(path.resolve(statePath))) {
    throw new Error('Checkpoint do Vibes aponta para um diretório de trabalho inválido.');
  }
  return state;
}

function videoStateResult(statePath, state) {
  const filePaths = [...new Set(state.filePaths || [])]
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  return {
    jobId: state.jobId,
    pollingUrl: statePath,
    projectUrl: state.projectUrl,
    status: state.status,
    filePath: filePaths[0] || '',
    filePaths,
    contentType: 'video/mp4',
    error: state.status === 'failed' ? state.lastError : null,
    downloadErrors: state.downloadErrors || {},
  };
}

// Persistência do projeto Vibes por projeto do storytelling (espelha a
// conversa única da Bíblia Visual): todas as submissões com o mesmo
// projectKey reabrem o MESMO projeto, em vez de criar um novo por remessa.
function vibesProjectStatePath(profilePath, projectKey) {
  const key = crypto.createHash('sha256').update(String(projectKey || 'default')).digest('hex');
  return path.join(profilePath, 'Storytelling', 'vibes-projects', `${key}.json`);
}

function reusableVibesProjectUrl(value) {
  try {
    const url = new URL(String(value || ''));
    return url.protocol === 'https:'
      && ['vibes.ai', 'www.vibes.ai'].includes(url.hostname)
      && /\/projects\//.test(url.pathname);
  } catch {
    return false;
  }
}

async function loadVibesProjectUrl(profilePath, projectKey) {
  if (!projectKey) return null;
  const statePath = vibesProjectStatePath(profilePath, projectKey);
  const state = await fs.readFile(statePath, 'utf8').then(JSON.parse).catch(() => ({}));
  return reusableVibesProjectUrl(state.url) ? state.url : null;
}

async function saveVibesProjectUrl(profilePath, projectKey, url) {
  if (!projectKey || !reusableVibesProjectUrl(url)) return;
  const statePath = vibesProjectStatePath(profilePath, projectKey);
  await fs.mkdir(path.dirname(statePath), { recursive: true });
  await fs.writeFile(statePath, JSON.stringify({ url, updatedAt: new Date().toISOString() }));
}

async function submitVideo(payload) {
  // Fechamento manual do navegador é definitivo (mesma regra da Bíblia Visual).
  await rejectIfUserClosed(payload.profilePath);
  // Submission is intentionally short-lived. Vibes continues generation server-side,
  // while subsequent polls reopen this exact project using the durable checkpoint.
  const { context, page } = await persistentPage(payload.profilePath, false);
  const stopUserCloseWatch = watchUserBrowserClose(context, payload.profilePath);
  const jobId = crypto.randomUUID();
  const workDir = path.resolve(payload.outputDir, jobId);
  const statePath = videoStatePath(workDir);
  await fs.mkdir(workDir, { recursive: true });
  try {
    // Projeto Vibes persistido por projeto do storytelling: na primeira
    // submissão um projeto é criado; nas seguintes ele é REABERTO. Assim
    // todas as remessas de vídeo ficam no mesmo projeto no Vibes.
    const savedProjectUrl = await loadVibesProjectUrl(payload.profilePath, payload.projectKey);
    // Timeout de navegação explícito (30s): o default de 15s da página derruba
    // o goto em redes oscilantes antes de qualquer retry próprio.
    if (savedProjectUrl) {
      await page.goto(savedProjectUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await settlePage(page);
      await ensureAuthorized(page, { autoLogin: true });
    } else {
      await page.goto(VIBES_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await settlePage(page);
      await ensureAuthorized(page, { autoLogin: true });
    }
    let textbox = await openVideoEditor(page, workDir);
    const durationConfigured = await configureVideoDuration(page, payload.duration_seconds);
    await uploadVideoInputs(page, payload, workDir);
    textbox = await waitForVideoPromptTextbox(page, 30000);
    if (!textbox) {
      throw new Error('O editor de vídeo do Vibes desapareceu após carregar os frames.');
    }
    await textbox.fill(payload.prompt);
    const oldSources = await page.locator('video, video source').evaluateAll(elements => elements
      .map(element => element.currentSrc || element.src).filter(Boolean));
    await page.getByRole('button', { name: /gerar|generate|criar|create/i }).last().click();
    await page.waitForURL(/\/projects\//, { timeout: 30000 }).catch(() => {});
    const projectUrl = page.url();
    if (!/\/projects\//.test(new URL(projectUrl).pathname)) {
      throw new Error('O Vibes não abriu um projeto identificável após a submissão.');
    }
    // Persiste o projeto para as PRÓXIMAS submissões do mesmo storytelling
    // (o poll deste job já reabre via checkpoint abaixo).
    await saveVibesProjectUrl(payload.profilePath, payload.projectKey, projectUrl);
    const state = {
      version: 2,
      jobId,
      status: 'pending',
      projectUrl,
      workDir,
      previousSources: [...new Set(oldSources)],
      discoveredSources: [],
      filePaths: [],
      downloadErrors: {},
      submittedAt: new Date().toISOString(),
      lastError: null,
      providerDurationSeconds: Number(payload.duration_seconds || 10),
      outputDurationSeconds: Number(payload.output_duration_seconds || 8),
      durationConfigured,
    };
    await saveVideoState(statePath, state);
    return videoStateResult(statePath, state);
  } finally {
    stopUserCloseWatch();
    // Ciclo por segmento espelhado da Bíblia Visual: submissão é curta e o
    // navegador FECHA imediatamente após registrar o checkpoint. Os polls
    // seguintes reabrem o projeto persistido (mesmo projeto no Vibes).
    await closePersistentSession(context);
  }
}

async function pollVideo(payload) {
  // Fechamento manual do navegador é definitivo: um poll NÃO reabre o
  // navegador quando o usuário fechou a janela. O erro tipado sobe ao worker
  // e encerra o ciclo de polling sem nova tentativa de abertura.
  await rejectIfUserClosed(payload.profilePath);
  const statePath = path.resolve(String(payload.statePath || ''));
  const state = await loadVideoState(statePath);
  state.filePaths = (state.filePaths || []).filter(Boolean);
  if (state.status === 'completed' || state.status === 'failed') {
    return videoStateResult(statePath, state);
  }

  let context;
  let page;
  try {
    ({ context, page } = await persistentPage(payload.profilePath, false));
    await page.goto(state.projectUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await settlePage(page);
    await ensureAuthorized(page, { autoLogin: true });

    const previous = new Set(state.previousSources || []);
    state.discoveredSources = (await videoSources(page))
      .filter(source => !previous.has(source));

    for (let sourceIndex = 0; sourceIndex < state.discoveredSources.length; sourceIndex += 1) {
      if (state.filePaths.length >= 4) break;
      const source = state.discoveredSources[sourceIndex];
      const filePath = path.resolve(state.workDir, `result-${sourceIndex + 1}.mp4`);
      if (await fs.stat(filePath).then(item => item.isFile() && item.size > 0).catch(() => false)) {
        if (!state.filePaths.includes(filePath)) state.filePaths.push(filePath);
        continue;
      }
      try {
        const downloaded = await mediaBytes(page, source);
        const isMp4 = downloaded.bytes?.length >= 12
          && downloaded.bytes.subarray(4, 8).toString('ascii') === 'ftyp';
        if (!isMp4) throw new Error('arquivo vazio, corrompido ou incompatível');
        await fs.writeFile(filePath, downloaded.bytes);
        state.filePaths.push(filePath);
        delete state.downloadErrors[source];
        await saveVideoState(statePath, state);
      } catch (error) {
        state.downloadErrors[source] = error instanceof Error ? error.message : String(error);
      }
    }

    if (state.filePaths.length >= 4) {
      state.status = 'completed';
      state.completedAt = new Date().toISOString();
      state.lastError = null;
    } else {
      state.status = 'pending';
      state.lastError = null;
    }
    if (state.filePaths.length > Number(state.lastObservedFileCount || 0)) {
      state.firstResultAt ||= new Date().toISOString();
      state.lastNewResultAt = new Date().toISOString();
      state.stableResultPolls = 0;
    } else if (state.filePaths.length > 0) {
      state.stableResultPolls = Number(state.stableResultPolls || 0) + 1;
    }
    state.lastObservedFileCount = state.filePaths.length;
    if (state.status === 'pending' && state.filePaths.length > 0 && state.stableResultPolls >= 2) {
      state.status = 'completed';
      state.partial = state.filePaths.length < 4;
      state.completedAt = new Date().toISOString();
    }
  } catch (error) {
    // Navigation/context replacement is recoverable because the project URL and every
    // successful download have already been checkpointed.
    state.lastError = error instanceof Error ? error.message : String(error);
    const diagnosticPath = path.resolve(state.workDir, `poll-error-${Date.now()}.png`);
    if (page && !page.isClosed()) {
      const diagnosticSaved = await page.screenshot({ path: diagnosticPath, fullPage: true })
        .then(() => true)
        .catch(() => false);
      if (diagnosticSaved) state.lastDiagnostic = diagnosticPath;
    }
  } finally {
    if (context) {
      // Espelha o ciclo da Bíblia Visual: quando o segmento chegou a um estado
      // terminal (completed/failed) OU expirou o prazo total, FECHA o navegador
      // imediatamente. Entre polls pendentes o navegador fica quente, pois a
      // espera do vídeo atravessa vários polls curtos.
      const terminal = state.status === 'completed' || state.status === 'failed';
      const elapsedMs = Date.now() - Date.parse(state.submittedAt);
      const deadlineMs = Math.max(5 * 60 * 1000, Number(payload.deadlineSeconds || 1800) * 1000);
      if (terminal || elapsedMs >= deadlineMs) {
        await closePersistentSession(context);
      } else {
        await releasePersistentPage(context);
      }
    }
  }

  const elapsedMs = Date.now() - Date.parse(state.submittedAt);
  const deadlineMs = Math.max(5 * 60 * 1000, Number(payload.deadlineSeconds || 1800) * 1000);
  if (state.status === 'pending' && elapsedMs >= deadlineMs) {
    if (state.filePaths.length) {
      // Preserve useful partial results instead of discarding an entire generation.
      state.status = 'completed';
      state.partial = true;
      state.completedAt = new Date().toISOString();
    } else {
      state.status = 'failed';
      state.lastError = state.lastError
        || 'O Vibes não apresentou vídeos acessíveis antes do tempo limite.';
    }
  }
  await saveVideoState(statePath, state);
  return videoStateResult(statePath, state);
}

async function executeAction(action, payload) {
  return action === 'authorize'
    ? await authorizeAfterUserClose(payload)
    : action === 'generate-image'
      ? await generateImage(payload)
      : action === 'submit-video'
        ? await submitVideo(payload)
        : action === 'poll-video'
          ? await pollVideo(payload)
          : action === 'generate-video'
            ? await submitVideo(payload)
            : action === 'resume-after-close'
              ? await (async () => {
                await clearUserClosedState(payload.profilePath);
                return { resumed: true };
              })()
              : (() => { throw new Error(`Ação desconhecida: ${action}`); })();
}

async function serveBridge() {
  bridgeServerMode = true;
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  const activeRequests = new Set();
  for await (const line of lines) {
    if (!line.trim()) continue;
    const request = JSON.parse(line);
    const task = (async () => {
      try {
        const result = await executeAction(String(request.action || ''), request.payload || {});
        process.stdout.write(`${JSON.stringify({ id: request.id, result })}\n`);
      } catch (error) {
        process.stdout.write(`${JSON.stringify({
          id: request.id,
          error: error instanceof Error ? error.message : String(error),
        })}\n`);
      }
    })();
    activeRequests.add(task);
    task.finally(() => activeRequests.delete(task));
  }
  await Promise.allSettled([...activeRequests]);
  await closeManagedSessions();
}

const action = process.argv[2];
if (action === 'serve') {
  try {
    await serveBridge();
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
} else {
  try {
    const payload = await inputPayload();
    const result = await executeAction(action, payload);
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
