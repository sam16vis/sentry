import {Fragment, useState} from 'react';
import styled from '@emotion/styled';
import beautify from 'js-beautify';

import {OnboardingCodeSnippet} from 'sentry/components/onboarding/gettingStartedDoc/onboardingCodeSnippet';
import {t} from 'sentry/locale';
import {space} from 'sentry/styles/space';

export enum StepType {
  INSTALL = 'install',
  CONFIGURE = 'configure',
  VERIFY = 'verify',
}

export const StepTitle = {
  [StepType.INSTALL]: t('Install'),
  [StepType.CONFIGURE]: t('Configure SDK'),
  [StepType.VERIFY]: t('Verify'),
};

interface CodeSnippetTab {
  code: string;
  label: string;
  language: string;
  value: string;
}

interface TabbedCodeSnippetProps {
  /**
   * An array of tabs to be displayed
   */
  tabs: CodeSnippetTab[];
  /**
   * A callback to be invoked when the configuration is copied to the clipboard
   */
  onCopy?: () => void;
  /**
   * A callback to be invoked when the configuration is selected and copied to the clipboard
   */
  onSelectAndCopy?: () => void;
  /**
   * Whether or not the configuration or parts of it are currently being loaded
   */
  partialLoading?: boolean;
}

function TabbedCodeSnippet({
  tabs,
  onCopy,
  onSelectAndCopy,
  partialLoading,
}: TabbedCodeSnippetProps) {
  const [selectedTabValue, setSelectedTabValue] = useState(tabs[0].value);
  const selectedTab = tabs.find(tab => tab.value === selectedTabValue) ?? tabs[0];
  const {code, language} = selectedTab;

  return (
    <OnboardingCodeSnippet
      dark
      language={language}
      onCopy={onCopy}
      onSelectAndCopy={onSelectAndCopy}
      hideCopyButton={partialLoading}
      disableUserSelection={partialLoading}
      tabs={tabs}
      selectedTab={selectedTabValue}
      onTabClick={value => setSelectedTabValue(value)}
    >
      {language === 'javascript'
        ? beautify.js(code, {
            indent_size: 2,
            e4x: true,
            brace_style: 'preserve-inline',
          })
        : code.trim()}
    </OnboardingCodeSnippet>
  );
}

type ConfigurationType = {
  /**
   * Additional information to be displayed below the code snippet
   */
  additionalInfo?: React.ReactNode;
  /**
   * The code snippet to display
   */
  code?: string | CodeSnippetTab[];
  /**
   * Nested configurations provide a convenient way to accommodate diverse layout styles, like the Spring Boot configuration.
   */
  configurations?: ConfigurationType[];
  /**
   * A brief description of the configuration
   */
  description?: React.ReactNode;
  /**
   * The language of the code to be rendered (python, javascript, etc)
   */
  language?: string;
  /**
   * A callback to be invoked when the configuration is copied to the clipboard
   */
  onCopy?: () => void;
  /**
   * A callback to be invoked when the configuration is selected and copied to the clipboard
   */
  onSelectAndCopy?: () => void;
  /**
   * Whether or not the configuration or parts of it are currently being loaded
   */
  partialLoading?: boolean;
};

interface BaseStepProps {
  /**
   * Additional information to be displayed below the configurations
   */
  additionalInfo?: React.ReactNode;
  configurations?: ConfigurationType[];
  /**
   * A brief description of the step
   */
  description?: React.ReactNode;
}
interface StepPropsWithTitle extends BaseStepProps {
  title: string;
  type?: undefined;
}

interface StepPropsWithoutTitle extends BaseStepProps {
  type: StepType;
  title?: undefined;
}

export type StepProps = StepPropsWithTitle | StepPropsWithoutTitle;

function getConfiguration({
  description,
  code,
  language,
  additionalInfo,
  onCopy,
  onSelectAndCopy,
  partialLoading,
}: ConfigurationType) {
  return (
    <Configuration>
      {description && <Description>{description}</Description>}
      {Array.isArray(code) ? (
        <TabbedCodeSnippet
          tabs={code}
          onCopy={onCopy}
          onSelectAndCopy={onSelectAndCopy}
          partialLoading={partialLoading}
        />
      ) : (
        language &&
        code && (
          <OnboardingCodeSnippet
            dark
            language={language}
            onCopy={onCopy}
            onSelectAndCopy={onSelectAndCopy}
            hideCopyButton={partialLoading}
            disableUserSelection={partialLoading}
          >
            {language === 'javascript'
              ? beautify.js(code, {
                  indent_size: 2,
                  e4x: true,
                  brace_style: 'preserve-inline',
                })
              : code.trim()}
          </OnboardingCodeSnippet>
        )
      )}
      {additionalInfo && <AdditionalInfo>{additionalInfo}</AdditionalInfo>}
    </Configuration>
  );
}

export function Step({
  title,
  type,
  configurations,
  additionalInfo,
  description,
}: StepProps) {
  return (
    <div>
      <h4>{title ?? StepTitle[type]}</h4>
      {description && <Description>{description}</Description>}
      {!!configurations?.length && (
        <Configurations>
          {configurations.map((configuration, index) => {
            if (configuration.configurations) {
              return (
                <Fragment key={index}>
                  {getConfiguration(configuration)}
                  {configuration.configurations.map(
                    (nestedConfiguration, nestedConfigurationIndex) => (
                      <Fragment key={nestedConfigurationIndex}>
                        {getConfiguration(nestedConfiguration)}
                      </Fragment>
                    )
                  )}
                </Fragment>
              );
            }
            return <Fragment key={index}>{getConfiguration(configuration)}</Fragment>;
          })}
        </Configurations>
      )}
      {additionalInfo && <GeneralAdditionalInfo>{additionalInfo}</GeneralAdditionalInfo>}
    </div>
  );
}

const Configuration = styled('div')`
  display: flex;
  flex-direction: column;
  gap: 1rem;
`;

const Configurations = styled(Configuration)`
  margin-top: ${space(2)};
`;

const Description = styled(Configuration)`
  code {
    color: ${p => p.theme.pink400};
  }
`;

const AdditionalInfo = styled(Description)``;

const GeneralAdditionalInfo = styled(Description)`
  margin-top: ${space(2)};
`;
