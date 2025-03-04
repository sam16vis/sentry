// Mirrors src/sentry/utils/platform_categories.py
// When changing this file, make sure to keep src/sentry/utils/platform_categories.py in sync.

import {t} from 'sentry/locale';
import {PlatformKey} from 'sentry/types';

export enum PlatformCategory {
  FRONTEND,
  MOBILE,
  BACKEND,
  SERVERLESS,
  DESKTOP,
  OTHER,
}

export const popularPlatformCategories: PlatformKey[] = [
  'javascript',
  'javascript-react',
  'javascript-nextjs',
  'python-django',
  'python',
  'python-flask',
  'python-fastapi',
  'ruby-rails',
  'node-express',
  'php-laravel',
  'java',
  'java-spring-boot',
  'dotnet',
  'dotnet-aspnetcore',
  'csharp',
  'go',
  'php',
  'ruby',
  'node',
  'react-native',
  'javascript-angular',
  'javascript-vue',
  'android',
  'apple-ios',
  'flutter',
  'dart-flutter',
  'unity',
];

export const frontend: PlatformKey[] = [
  'dart',
  'javascript',
  'javascript-react',
  'javascript-angular',
  'javascript-angularjs',
  'javascript-backbone',
  'javascript-ember',
  'javascript-gatsby',
  'javascript-vue',
  'javascript-nextjs',
  'javascript-remix',
  'javascript-svelte',
  'javascript-sveltekit',
  'unity',
];

export const mobile: PlatformKey[] = [
  'android',
  'apple-ios',
  'cordova',
  'capacitor',
  'javascript-cordova',
  'javascript-capacitor',
  'ionic',
  'react-native',
  'flutter',
  'dart-flutter',
  'unity',
  'dotnet-maui',
  'dotnet-xamarin',
  'unreal',
  // Old platforms
  'java-android',
  'cocoa-objc',
  'cocoa-swift',
];

export const backend: PlatformKey[] = [
  'bun',
  'dotnet',
  'dotnet-aspnetcore',
  'dotnet-aspnet',
  'elixir',
  'go',
  'go-http',
  'java',
  'java-appengine',
  'java-log4j',
  'java-log4j2',
  'java-logback',
  'java-logging',
  'java-spring',
  'java-spring-boot',
  'native',
  'node',
  'node-express',
  'node-koa',
  'node-connect',
  'perl',
  'php',
  'php-laravel',
  'php-monolog',
  'php-symfony',
  'python',
  'python-django',
  'python-flask',
  'python-fastapi',
  'python-starlette',
  'python-sanic',
  'python-celery',
  'python-aiohttp',
  'python-chalice',
  'python-falcon',
  'python-quart',
  'python-tryton',
  'python-wsgi',
  'python-asgi',
  'python-bottle',
  'python-pylons',
  'python-pyramid',
  'python-tornado',
  'python-rq',
  'python-pymongo',
  'ruby',
  'ruby-rails',
  'ruby-rack',
  'rust',
  'kotlin',
];

export const serverless: PlatformKey[] = [
  'python-awslambda',
  'python-azurefunctions',
  'python-gcpfunctions',
  'python-serverless',
  'node-awslambda',
  'node-azurefunctions',
  'node-gcpfunctions',
  'dotnet-awslambda',
  'dotnet-gcpfunctions',
];

export const desktop: PlatformKey[] = [
  'apple-macos',
  'dotnet',
  'dotnet-winforms',
  'dotnet-wpf',
  'dotnet-maui',
  'java',
  'electron',
  'javascript-electron',
  'native',
  'native-crashpad',
  'native-breakpad',
  'native-minidump',
  'native-qt',
  'minidump',
  'unity',
  'flutter',
  'kotlin',
  'unreal',
];

const categoryList = [
  {id: 'popular', name: t('Popular'), platforms: popularPlatformCategories},
  {id: 'browser', name: t('Browser'), platforms: frontend},
  {id: 'server', name: t('Server'), platforms: backend},
  {id: 'mobile', name: t('Mobile'), platforms: mobile},
  {id: 'desktop', name: t('Desktop'), platforms: desktop},
  {id: 'serverless', name: t('Serverless'), platforms: serverless},
] as const;

export const deprecatedPlatforms = new Set<PlatformKey>([
  'node-serverlesscloud',
  'python-pylons',
  'python-pymongo',
]);

export const sourceMaps: PlatformKey[] = [
  ...frontend,
  'react-native',
  'cordova',
  'electron',
];

export const tracing = [
  'python-tracing',
  'node-tracing',
  'react-native-tracing',
] as const;

export const performance: PlatformKey[] = [
  'bun',
  'javascript',
  'javascript-ember',
  'javascript-react',
  'javascript-vue',
  'php',
  'php-laravel',
  'python',
  'python-django',
  'python-flask',
  'python-fastapi',
  'python-starlette',
  'python-sanic',
  'python-celery',
  'python-bottle',
  'python-pylons',
  'python-pyramid',
  'python-tornado',
  'python-rq',
  'node',
  'node-express',
  'node-koa',
  'node-connect',
];

// List of platforms that have performance onboarding checklist content
export const withPerformanceOnboarding: Set<PlatformKey> = new Set([
  'javascript',
  'javascript-react',
]);

// List of platforms that do not have performance support. We make use of this list in the product to not provide any Performance
// views such as Performance onboarding checklist.
export const withoutPerformanceSupport: Set<PlatformKey> = new Set([
  'elixir',
  'minidump',
]);

export const profiling: PlatformKey[] = [
  // mobile
  'android',
  'apple-ios',
  // go
  'go',
  // nodejs
  'node',
  'node-express',
  'node-koa',
  'node-connect',
  'javascript-nextjs',
  'javascript-remix',
  'javascript-sveltekit',
  'javascript',
  'javascript-react',
  // react-native
  'react-native',
  // python
  'python',
  'python-django',
  'python-flask',
  'python-fastapi',
  'python-starlette',
  'python-sanic',
  'python-celery',
  'python-bottle',
  'python-pylons',
  'python-pyramid',
  'python-tornado',
  'python-rq',
  'python-aiohttp',
  'python-chalice',
  'python-falcon',
  'python-quart',
  'python-tryton',
  'python-wsgi',
  'python-serverless',
  // rust
  'rust',
  // php
  'php',
  'php-laravel',
  'php-symfony',
  // ruby
  'ruby',
  'ruby-rails',
  'ruby-rack',
];

export const releaseHealth: PlatformKey[] = [
  // frontend
  'javascript',
  'javascript-react',
  'javascript-angular',
  'javascript-angularjs',
  'javascript-backbone',
  'javascript-ember',
  'javascript-gatsby',
  'javascript-vue',
  'javascript-nextjs',
  'javascript-remix',
  'javascript-svelte',
  'javascript-sveltekit',
  // mobile
  'android',
  'apple-ios',
  'cordova',
  'javascript-cordova',
  'react-native',
  'flutter',
  'dart-flutter',
  // backend
  'bun',
  'native',
  'node',
  'node-express',
  'node-koa',
  'node-connect',
  'python',
  'python-django',
  'python-flask',
  'python-fastapi',
  'python-starlette',
  'python-sanic',
  'python-celery',
  'python-bottle',
  'python-pylons',
  'python-pyramid',
  'python-tornado',
  'python-rq',
  'python-pymongo',
  'rust',
  // serverless
  // desktop
  'apple-macos',
  'native',
  'native-crashpad',
  'native-breakpad',
  'native-qt',
];

export const replayPlatforms: readonly PlatformKey[] = [
  'capacitor',
  'electron',
  'javascript-angular',
  // 'javascript-angularjs', // Unsupported, angularjs requires the v6.x core SDK
  'javascript-backbone',
  'javascript-capacitor',
  'javascript-electron',
  'javascript-ember',
  'javascript-gatsby',
  'javascript-nextjs',
  'javascript-react',
  'javascript-remix',
  'javascript-svelte',
  'javascript-sveltekit',
  'javascript-vue',
  'javascript',
];

/**
 * The list of platforms for which we have created onboarding instructions.
 * Should be a subset of the list of `replayPlatforms`.
 * This should match sentry-docs: `/src/wizard/${platform}/replay-onboarding/${subPlatform}/`.
 * See: https://github.com/getsentry/sentry-docs/tree/master/src/wizard/javascript/replay-onboarding
 */
export const replayOnboardingPlatforms: readonly PlatformKey[] = [
  'capacitor',
  'electron',
  'javascript-angular',
  // 'javascript-angularjs', // Unsupported, angularjs requires the v6.x core SDK
  // 'javascript-backbone', // No docs yet
  'javascript-capacitor',
  'javascript-electron',
  'javascript-ember',
  'javascript-gatsby',
  'javascript-nextjs',
  'javascript-react',
  'javascript-remix',
  'javascript-svelte',
  'javascript-sveltekit',
  'javascript-vue',
  'javascript',
];

/**
 * Additional aliases used for filtering in the platform picker
 */
export const filterAliases: Partial<Record<PlatformKey, string[]>> = {
  native: ['cpp', 'c++'],
};

export default categoryList;

export type Platform = {
  key: PlatformKey;
  id?: string;
  link?: string | null;
  name?: string;
};
