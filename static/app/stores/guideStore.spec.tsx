import ConfigStore from 'sentry/stores/configStore';
import GuideStore from 'sentry/stores/guideStore';
import {trackAnalytics} from 'sentry/utils/analytics';

jest.mock('sentry/utils/analytics');

describe('GuideStore', function () {
  let data;

  beforeEach(function () {
    jest.clearAllMocks();
    ConfigStore.config = TestStubs.Config({
      user: TestStubs.User({
        id: '5',
        isSuperuser: false,
        dateJoined: new Date(2020, 0, 1),
      }),
    });
    GuideStore.init();
    data = [
      {
        guide: 'issue',
        seen: false,
      },
      {guide: 'issue_stream', seen: true},
    ];
    GuideStore.registerAnchor('issue_number');
    GuideStore.registerAnchor('exception');
    GuideStore.registerAnchor('breadcrumbs');
    GuideStore.registerAnchor('issue_stream');
  });

  afterEach(() => {
    GuideStore.teardown();
  });

  it('should move through the steps in the guide', function () {
    GuideStore.fetchSucceeded(data);
    // Should pick the first non-seen guide in alphabetic order.
    expect(GuideStore.getState().currentStep).toEqual(0);
    expect(GuideStore.getState().currentGuide?.guide).toEqual('issue');
    // Should prune steps that don't have anchors.
    expect(GuideStore.getState().currentGuide?.steps).toHaveLength(3);

    GuideStore.nextStep();
    expect(GuideStore.getState().currentStep).toEqual(1);
    GuideStore.nextStep();
    expect(GuideStore.getState().currentStep).toEqual(2);
    GuideStore.closeGuide();
    expect(GuideStore.getState().currentGuide).toEqual(null);
  });

  it('should force show a guide with #assistant', function () {
    data = [
      {
        guide: 'issue',
        seen: true,
      },
      {guide: 'issue_stream', seen: false},
    ];

    GuideStore.fetchSucceeded(data);
    window.location.hash = '#assistant';
    window.dispatchEvent(new Event('load'));
    expect(GuideStore.getState().currentGuide?.guide).toEqual('issue');
    GuideStore.closeGuide();
    expect(GuideStore.getState().currentGuide?.guide).toEqual('issue_stream');
    window.location.hash = '';
  });

  it('should force hide', function () {
    expect(GuideStore.state.forceHide).toEqual(false);
    GuideStore.setForceHide(true);
    expect(GuideStore.state.forceHide).toEqual(true);
    GuideStore.setForceHide(false);
    expect(GuideStore.state.forceHide).toEqual(false);
  });

  it('should record analytics events when guide is cued', function () {
    const spy = jest.spyOn(GuideStore, 'recordCue');
    GuideStore.fetchSucceeded(data);
    expect(spy).toHaveBeenCalledWith('issue');

    expect(trackAnalytics).toHaveBeenCalledWith('assistant.guide_cued', {
      guide: 'issue',
      organization: null,
    });

    expect(spy).toHaveBeenCalledTimes(1);

    window.dispatchEvent(new Event('load'));
    expect(spy).toHaveBeenCalledTimes(1);

    GuideStore.nextStep();
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it('only shows guides with server data and content', function () {
    data = [
      {
        guide: 'issue',
        seen: true,
      },
      {
        guide: 'has_no_content',
        seen: false,
      },
    ];

    GuideStore.fetchSucceeded(data);
    expect(GuideStore.state.guides.length).toBe(1);
    expect(GuideStore.state.guides[0].guide).toBe(data[0].guide);
  });
});
