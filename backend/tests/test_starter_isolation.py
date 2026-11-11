from tests.base import ApiTest


class StarterIsolationTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.app.config['SEED_NEW_RESTAURANTS'] = True

    def test_new_accounts_start_identical_but_are_independent(self):
        a = self.register('Restaurant A', 'a@example.com')
        b = self.register('Restaurant B', 'b@example.com')
        def items(token, path):
            return self.call('get', path, token, expect=200).get_json()['items']
        am, bm = items(a, '/menu-items'), items(b, '/menu-items')
        self.assertEqual([x['name'] for x in am], [x['name'] for x in bm])
        self.assertEqual(len(am), 8)
        at, bt = items(a, '/tables'), items(b, '/tables')
        self.assertEqual([x['label'] for x in at], [x['label'] for x in bt])
        self.assertEqual(len(at), 16)
        self.assertTrue(all(t['status'] == 'available' for t in at + bt))
        self.assertNotEqual(am[0]['id'], bm[0]['id'])
        self.assertNotEqual(at[0]['id'], bt[0]['id'])
        self.assertEqual(items(a, '/orders'), [])
        self.assertEqual(items(b, '/orders'), [])
        categories = items(a, '/categories')
        self.call('post', '/menu-items', a, {'category_id': categories[0]['id'], 'name': 'Only A', 'price': 500}, 201)
        self.assertIn('Only A', [x['name'] for x in items(a, '/menu-items')])
        self.assertNotIn('Only A', [x['name'] for x in items(b, '/menu-items')])
