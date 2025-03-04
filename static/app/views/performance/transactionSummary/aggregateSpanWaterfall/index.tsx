import {Fragment} from 'react';
import styled from '@emotion/styled';

import Feature from 'sentry/components/acl/feature';
import Alert from 'sentry/components/alert';
import {AggregateSpans} from 'sentry/components/events/interfaces/spans/aggregateSpans';
import * as Layout from 'sentry/components/layouts/thirds';
import {t} from 'sentry/locale';
import {defined} from 'sentry/utils';
import EventView from 'sentry/utils/discover/eventView';
import {decodeScalar} from 'sentry/utils/queryString';
import {useLocation} from 'sentry/utils/useLocation';
import useOrganization from 'sentry/utils/useOrganization';
import useProjects from 'sentry/utils/useProjects';
import Tab from 'sentry/views/performance/transactionSummary/tabs';

import PageLayout from '../pageLayout';

function renderNoAccess() {
  return (
    <Layout.Page withPadding>
      <Alert type="warning">{t("You don't have access to this feature")}</Alert>
    </Layout.Page>
  );
}

function AggregateSpanWaterfall(): React.ReactElement {
  const location = useLocation();
  const organization = useOrganization();
  const projects = useProjects();

  const transaction = decodeScalar(location.query.transaction);
  return (
    <Feature
      features={['starfish-aggregate-span-waterfall']}
      organization={organization}
      renderDisabled={renderNoAccess}
    >
      <PageLayout
        location={location}
        organization={organization}
        projects={projects.projects}
        tab={Tab.AGGREGATE_WATERFALL}
        generateEventView={() => EventView.fromLocation(location)}
        getDocumentTitle={() => t(`Aggregate Waterfall: %s`, transaction)}
        childComponent={() => {
          return (
            <Fragment>
              <TitleWrapper>{t('Aggregate Span Waterfall')}</TitleWrapper>
              <Layout.Main>
                {defined(transaction) && <AggregateSpans transaction={transaction} />}
              </Layout.Main>
            </Fragment>
          );
        }}
      />
    </Feature>
  );
}

export default AggregateSpanWaterfall;

const TitleWrapper = styled('div')`
  padding: 0px 30px 0px 0px;
  font-size: ${p => p.theme.headerFontSize};
  font-weight: bold;
  margin-top: 20px;
`;
