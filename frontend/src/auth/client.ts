import Keycloak from 'keycloak-js'

/** Minimum remaining validity (seconds) before a token is refreshed on use. */
const MIN_VALIDITY = 30

let keycloak: Keycloak | null = null

function instance(): Keycloak {
  if (!keycloak) {
    keycloak = new Keycloak({
      url: import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8080',
      realm: import.meta.env.VITE_KEYCLOAK_REALM ?? 'ekb',
      clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? 'ekb-frontend',
    })
    keycloak.onTokenExpired = () => {
      void keycloak?.updateToken(MIN_VALIDITY).catch(() => keycloak?.login())
    }
  }
  return keycloak
}

const IDP_PARAM = 'idp'
const BRIDGE_IDPS = ['wecom', 'dingtalk']

/**
 * Keycloak identity provider to skip the login page with: `?idp=wecom|dingtalk` in the URL
 * (e.g. the workbench app link), or `wecom` automatically inside the WeCom client.
 * `?idp=none` forces the normal login page (escape hatch when scan login fails).
 */
function idpHint(): string | undefined {
  const requested = new URLSearchParams(window.location.search).get(IDP_PARAM)
  if (requested) return BRIDGE_IDPS.includes(requested) ? requested : undefined
  if (/wxwork/i.test(navigator.userAgent)) return 'wecom'
  return undefined
}

function cleanRedirectUri(): string {
  const url = new URL(window.location.href)
  url.searchParams.delete(IDP_PARAM)
  return url.toString()
}

function redirectToLogin(): Promise<void> {
  return instance().login({ idpHint: idpHint(), redirectUri: cleanRedirectUri() })
}

/** Authorization Code + PKCE login; redirects to Keycloak when there is no session. */
export async function initAuth(): Promise<void> {
  const authenticated = await instance().init({
    pkceMethod: 'S256',
    checkLoginIframe: false,
  })
  if (!authenticated) {
    await redirectToLogin()
    // The page is navigating away; never resolve so the app is not mounted meanwhile.
    await new Promise<never>(() => undefined)
  }
}

/** Returns a token valid for at least MIN_VALIDITY seconds, refreshing if needed. */
export async function getValidToken(): Promise<string | undefined> {
  const kc = instance()
  if (!kc.authenticated) return undefined
  try {
    await kc.updateToken(MIN_VALIDITY)
  } catch {
    await kc.login()
    return undefined
  }
  return kc.token
}

export async function login(): Promise<void> {
  await redirectToLogin()
}

export async function logout(): Promise<void> {
  await instance().logout({ redirectUri: window.location.origin })
}
