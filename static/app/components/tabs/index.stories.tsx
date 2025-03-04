import {Fragment, useState} from 'react';
import range from 'lodash/range';

import Matrix from 'sentry/components/stories/matrix';
import SideBySide from 'sentry/components/stories/sideBySide';
import SizingWindow from 'sentry/components/stories/sizingWindow';
import {TabList, TabPanels, Tabs} from 'sentry/components/tabs';
import storyBook from 'sentry/stories/storyBook';

export default storyBook(Tabs, story => {
  const TABS = [
    {key: 'one', label: 'One', content: 'This is the first Panel.'},
    {key: 'two', label: 'Two', content: 'This is the second panel'},
    {key: 'three', label: 'Three', content: 'This is the third panel'},
  ];

  story('Default', () => (
    <Fragment>
      <p>
        You should be using all of <var>{'<Tabs>'}</var>, <var>{'<TabList>'}</var>,{' '}
        <var>{'<TabList.Item>'}</var>, <var>{'<TabPanels>'}</var> and
        <var>{'<TabPanels.Item>'}</var> components.
      </p>
      <p>
        This will give you all kinds of accessibility and state tracking out of the box.
        But you will have to render all tab content, including hooks, upfront.
      </p>
      <SizingWindow>
        <Tabs>
          <TabList>
            {TABS.map(tab => (
              <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
            ))}
          </TabList>
          <TabPanels>
            {TABS.map(tab => (
              <TabPanels.Item key={tab.key}>{tab.content}</TabPanels.Item>
            ))}
          </TabPanels>
        </Tabs>
      </SizingWindow>
    </Fragment>
  ));

  story('Items Overflow', () => {
    const tabs = range(65, 75).map(i => ({
      key: 'i' + i,
      label: String.fromCharCode(i, i, i, i),
      content: String.fromCharCode(i, i, i, i),
    }));
    return (
      <Fragment>
        <p>When there are many items, they will overflow into a dropdown menu.</p>
        <SizingWindow display="block" style={{height: '210px', width: '400px'}}>
          <Tabs defaultValue="two">
            <TabList>
              {tabs.map(tab => (
                <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
              ))}
            </TabList>
          </Tabs>
        </SizingWindow>
      </Fragment>
    );
  });

  story('Default Value', () => (
    <Fragment>
      <p>
        Set <var>{'<Tabs defaultValue="...">'}</var>
      </p>
      <SizingWindow>
        <Tabs defaultValue="two">
          <TabList>
            {TABS.map(tab => (
              <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
            ))}
          </TabList>
          <TabPanels>
            {TABS.map(tab => (
              <TabPanels.Item key={tab.key}>{tab.content}</TabPanels.Item>
            ))}
          </TabPanels>
        </Tabs>
      </SizingWindow>
    </Fragment>
  ));

  story('Controlled Value', () => {
    const [selected, setSelected] = useState('two');
    return (
      <Fragment>
        <p>
          If you want to control the state of the tabs from outside, you can call{' '}
          <var>{'useState()'}</var> and set{' '}
          <var>{'<Tabs value={selected} onChange={selected => ...}>'}</var> manually.
        </p>
        <p>
          This is useful if you want to detect button clicks and do something different.{' '}
          The <var>{'<Tabs>'}</var> context wrapper is not required in this case.
        </p>
        <p>selected={selected}</p>
        <SizingWindow>
          <Tabs value={selected} onChange={setSelected}>
            <TabList>
              {TABS.map(tab => (
                <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
              ))}
            </TabList>
            <TabPanels>
              {TABS.map(tab => (
                <TabPanels.Item key={tab.key}>{tab.content}</TabPanels.Item>
              ))}
            </TabPanels>
          </Tabs>
        </SizingWindow>
      </Fragment>
    );
  });

  story('Rendering', () => (
    <Matrix
      component={props => (
        <Tabs orientation={props.orientation}>
          <TabList hideBorder={props.hideBorder}>
            {TABS.map(tab => (
              <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
            ))}
          </TabList>
          <TabPanels>
            {TABS.map(tab => (
              <TabPanels.Item key={tab.key}>{tab.content}</TabPanels.Item>
            ))}
          </TabPanels>
        </Tabs>
      )}
      propMatrix={{
        orientation: ['horizontal', 'vertical'],
        hideBorder: [false, true],
      }}
      selectedProps={['orientation', 'hideBorder']}
    />
  ));

  story('Disabled', () => (
    <SideBySide>
      <div>
        <p>
          Use <var>&lt;Tabs disabled&gt;</var> to disable everything.
        </p>
        <SizingWindow>
          <Tabs disabled>
            <TabList>
              {TABS.map(tab => (
                <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
              ))}
            </TabList>
            <TabPanels>
              {TABS.map(tab => (
                <TabPanels.Item key={tab.key}>{tab.content}</TabPanels.Item>
              ))}
            </TabPanels>
          </Tabs>
        </SizingWindow>
      </div>
      <div>
        <p>
          Use <var>{'<TabList disabledKeys={[...]}>'}</var> to disable individual{' '}
          <var>{'<TabList.Item>'}</var> children.
        </p>
        <SizingWindow>
          <Tabs>
            <TabList disabledKeys={['two']}>
              {TABS.map(tab => (
                <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
              ))}
            </TabList>
            <TabPanels>
              {TABS.map(tab => (
                <TabPanels.Item key={tab.key}>{tab.content}</TabPanels.Item>
              ))}
            </TabPanels>
          </Tabs>
        </SizingWindow>
      </div>
    </SideBySide>
  ));
});
