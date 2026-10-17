import { config } from '@vue/test-utils'
import { i18n } from '@/i18n'

// Component specs assert on Chinese copy; individual specs may switch to 'en'.
i18n.global.locale.value = 'zh-CN'
config.global.plugins = [...(config.global.plugins ?? []), i18n]
