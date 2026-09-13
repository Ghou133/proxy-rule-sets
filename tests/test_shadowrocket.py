import configparser
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_shadowrocket import render, build, FILTER, SOURCES


def parse(text):
    config = configparser.ConfigParser(interpolation=None, delimiters=('=',), strict=True, allow_no_value=True)
    config.optionxform = str
    config.read_string(text)
    return config


class ShadowrocketTests(unittest.TestCase):
    def test_generated_files_match_builder_and_encoding(self):
        for mode in (True, False):
            name = 'with-landing.conf' if mode else 'without-landing.conf'
            content = (ROOT/'clients/shadowrocket'/name).read_bytes()
            self.assertEqual(content, render(mode).encode('utf-8'))
            self.assertFalse(content.startswith(b'\xef\xbb\xbf'))
            self.assertNotIn(b'\r', content)
            self.assertTrue(content.endswith(b'\n'))

    def test_group_order_choices_and_no_automatic_exit_bypass(self):
        config = parse(render(True))
        groups = config['Proxy Group']
        self.assertEqual(next(iter(groups)), 'Proxy')
        self.assertEqual(groups['Proxy'].split(',')[:4], ['select','Auto','Nodes','Exit'])
        self.assertEqual(groups['AI'], 'select,Exit,Proxy,policy-select-name=Exit')
        self.assertTrue(groups['Relay'].startswith('select,SUBSCRIPTION,use=true,'))
        self.assertTrue(groups['Transit'].startswith('fallback,Relay,Auto,'))
        self.assertNotIn('Latency',groups)
        self.assertEqual(config['General']['close-if-proxy-chain-missing'], 'true')

    def test_graph_has_no_cycle_or_unknown_reference(self):
        for mode in (True, False):
            config = parse(render(mode))
            graph = {name: [x for x in value.split(',')[1:] if '=' not in x]
                     for name,value in config['Proxy Group'].items()}
            if mode:
                # This edge must be bound in the app; it is not assumed installed by .conf import.
                graph['Exit'] = ['Transit']
            def visit(name, stack):
                if name in {'SUBSCRIPTION','REJECT'}: return
                self.assertIn(name, graph)
                self.assertNotIn(name, stack)
                for item in graph[name]: visit(item, stack | {name})
            for name in graph: visit(name, set())

    def test_no_landing_and_no_advertising(self):
        text = render(False)
        config = parse(text)
        self.assertNotIn('Proxy', config.sections())
        self.assertNotIn('Relay',config['Proxy Group'])
        self.assertNotIn('Exit',config['Proxy Group']['Proxy'])
        for mode in (True, False):
            rules = render(mode).split('[Rule]\n')[1].split('[Host]')[0]
            self.assertNotIn('REJECT', rules)
            self.assertNotIn('Advertising',rules)
            self.assertNotIn('/QuantumultX/',rules)
            self.assertIn('GEOIP,CN,DIRECT',rules)
            self.assertIn('FINAL,Proxy',rules)
            self.assertLess(rules.index(',AI'),rules.index(',DIRECT'))

    def test_subscription_filter_keeps_all_regions_and_service_suffixes(self):
        for name in ('Japan 01','Hong Kong 04','US GPT HY2','Singapore 优化'):
            self.assertIsNotNone(re.match(FILTER,name))
        for name in ('剩余流量 100GB','Traffic 100GB','套餐到期','Subscription Info','12.78 GB | 200 GB'):
            self.assertIsNone(re.match(FILTER,name))

    def test_private_output_cannot_enter_public_repo(self):
        with self.assertRaises(ValueError): build(options={'subscription':'Test'},output=ROOT/'private')
        with tempfile.TemporaryDirectory() as temp:
            output = build(options={'subscription':'Test'},output=temp)
            self.assertIn('Test,use=true',output['with-landing.conf'])

    def test_general_settings_and_clean_urls(self):
        config = parse(render(True))
        self.assertEqual(config['General']['block-quic'],'all-proxy')
        self.assertEqual(config['General']['dns-server'].split(',')[0],'https://doh.pub/dns-query')
        self.assertIn('*.local',config['General']['skip-proxy'])
        self.assertNotIn('\\*',render(True))
        self.assertNotIn('](',render(True))
        self.assertIn('DOMAIN-SET,'+SOURCES['ChinaDomain']+',DIRECT',render(True))
        self.assertEqual(len(SOURCES),4)

    def test_mobile_has_only_one_slow_shared_pool_and_one_light_monitor(self):
        groups=parse(render(True))['Proxy Group']
        tested={name:value for name,value in groups.items() if ',url=' in value}
        self.assertEqual(set(tested),{'Auto','Transit'})
        self.assertIn('interval=1800',tested['Auto'])
        self.assertIn('interval=300',tested['Transit'])
        self.assertEqual(tested['Transit'].split(',')[:3],['fallback','Relay','Auto'])
        self.assertFalse(any(value.startswith('url-test,') for value in groups.values()))
        self.assertNotIn(',url=',groups['Relay'])
        self.assertEqual([k for k in groups if 'hidden=1' not in groups[k]],['Proxy','AI','Relay'])


if __name__ == '__main__': unittest.main()
