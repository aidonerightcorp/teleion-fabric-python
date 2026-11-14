# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Strategy choices cannot remove declared budget exhaustion checks."""
import unittest
from stepkit import omninode as O

TASK = {'id': 'budget-stop', 'question': 'Return four'}

class BudgetStops(unittest.TestCase):
    def node(self, bounds, rules, evidence=False, arrangement=None):
        params = {'arrangement': arrangement or [['answer', 'take']]}
        resolver = O.Resolver(evidence={'stop_rules': {'value': rules, 'source': 'authored proposal'}} if evidence else {})
        if not evidence:
            params['stop_rules'] = rules
        return O.OmniNode(O.CONTRACT.with_(bounds), O.PARAMETERS.with_(params), resolver=resolver)

    def test_zero_budgets_survive_strategy_proposals(self):
        for field, opposite in [('budget.tokens', 'budget_model_seconds'), ('budget.model_seconds', 'budget_tokens')]:
            for rules in [[], [opposite]]:
                for evidence in [False, True]:
                    with self.subTest(field=field, rules=rules, evidence=evidence):
                        calls = []
                        source = O.PartsSource(None, {'answer': O.Part('answer', value=lambda task: calls.append(task) or 4)})
                        record = self.node({field: 0}, rules, evidence).run(TASK, source)
                        self.assertEqual(calls, [])
                        self.assertFalse(record.accepted)
                        self.assertEqual(record.steps, [])

    def test_unlimited_budget_keeps_strategy_flexibility(self):
        record = self.node({'budget.tokens': None, 'budget.model_seconds': None}, []).run(
            TASK, O.PartsSource(None, {'answer': O.Part('answer', value=lambda task: 4)}))
        self.assertTrue(record.accepted)
        self.assertEqual(record.answer, 4)

    def test_exhausted_budget_stops_next_stage(self):
        for field in ['budget.tokens', 'budget.model_seconds']:
            with self.subTest(field=field):
                calls = []
                def probe(call, task, seed=None):
                    calls.append(call)
                    return {'answer': None, 'ok': False, 'cost': {'model_s': 2, 'tok_in': 1, 'tok_out': 1}}
                source = O.PartsSource(probe, {'miss': O.Part('miss', calls=[{'call': 'measured'}]), 'answer': O.Part('answer', value=lambda task: calls.append('answer') or 4)})
                record = self.node({field: 2}, [], arrangement=[['miss', 'take'], ['answer', 'take']]).run(TASK, source)
                self.assertEqual(calls, ['measured'])
                self.assertFalse(record.accepted)
                self.assertEqual(len(record.steps), 1)

    def test_custom_strategy_still_applies(self):
        key = 'authored_stop'
        self.assertNotIn(key, O.STOP_RULES)
        O.STOP_RULES[key] = lambda node, spent: 'strategy stops this task'
        try:
            calls = []
            source = O.PartsSource(None, {'answer': O.Part('answer', value=lambda task: calls.append(task) or 4)})
            record = self.node({}, [key]).run(TASK, source)
            self.assertEqual(calls, [])
            self.assertIn('strategy stops', record.reason)
        finally:
            del O.STOP_RULES[key]

    def test_remaining_budget_allows_fallback_stage(self):
        record = self.node({'budget.tokens': 2, 'budget.model_seconds': 2}, [], arrangement=[['miss', 'take'], ['answer', 'take']]).run(
            TASK, O.PartsSource(None, {'miss': O.Part('miss', value=lambda task: None), 'answer': O.Part('answer', value=lambda task: 4)}))
        self.assertTrue(record.accepted)
        self.assertEqual([step.node for step in record.steps], ['miss', 'answer'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
