import type { LocaleModule } from '../index'

/** User guide page and guided tours. The manual and tour content live in `src/guide/content`. */
export default {
  'zh-CN': {
    view: {
      title: '使用说明',
      faq: '常见问题',
      tryIt: '去试试',
      playTour: '播放该页引导',
      noTour: '该页面暂无可播放的引导',
    },
    tour: {
      skip: '跳过引导',
    },
  },
  en: {
    view: {
      title: 'User guide',
      faq: 'FAQ',
      tryIt: 'Try it',
      playTour: 'Play page tour',
      noTour: 'No tour is available for this page',
    },
    tour: {
      skip: 'Skip tour',
    },
  },
} satisfies LocaleModule
