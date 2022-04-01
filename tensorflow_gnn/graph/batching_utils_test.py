"""Tests for batching_utils_test.py."""
import functools
import math

from absl.testing import parameterized
import tensorflow as tf
from tensorflow_gnn.graph import adjacency as adj
from tensorflow_gnn.graph import batching_utils
from tensorflow_gnn.graph import graph_tensor as gt
from tensorflow_gnn.graph import graph_tensor_test_utils as tu
from tensorflow_gnn.graph import preprocessing_common as preprocessing

as_tensor = tf.convert_to_tensor
as_ragged = tf.ragged.constant
SizeConstraints = preprocessing.SizeConstraints


class DynamicBatchTest(tu.GraphTensorTestBase):
  """Tests for context, node sets and edge sets creation."""

  @parameterized.parameters([
      dict(target_num_components=100, features={
          'id': as_tensor([1]),
      }),
      dict(
          target_num_components=3,
          features={
              'f1': as_tensor([1.]),
              'f2': as_tensor([[1., 2.]]),
              'i3': as_tensor([[[1, 2], [3, 4]]]),
              'r1': as_ragged([[], ['a', 'b']]),
          }),
  ])
  def testFeaturesBatching(self, target_num_components: int,
                           features: gt.Fields):
    source = gt.GraphTensor.from_pieces(
        gt.Context.from_fields(shape=[], features=features))
    dataset = tf.data.Dataset.from_tensors(source)
    dataset = dataset.repeat(target_num_components)
    dataset = batching_utils.dynamic_batch(
        dataset,
        SizeConstraints(
            total_num_components=target_num_components,
            total_num_nodes={},
            total_num_edges={}))
    result = list(dataset)
    self.assertLen(result, 1)
    result = result[0]
    self.assertAllEqual(result.shape, tf.TensorShape([target_num_components]))
    self.assertAllEqual(result.total_num_components, target_num_components)
    self.assertAllEqual(result.context.sizes, [[1]] * target_num_components)

    expected_features = tf.nest.map_structure(
        lambda f: tf.stack([f] * target_num_components, axis=0), features)
    self.assertFieldsEqual(result.context.features, expected_features)

  @parameterized.parameters([tf.data.UNKNOWN_CARDINALITY, 5])
  def testDynamicBatching1(self, cardinality):

    def generate(num_components):
      sizes = tf.ones([num_components], dtype=tf.int64)
      features = {'f': tf.fill([num_components, 2], value=.5)}
      return gt.GraphTensor.from_pieces(
          gt.Context.from_fields(features=features, sizes=sizes))

    dataset = tf.data.Dataset.from_tensor_slices([1, 0, 2, 3, 2])
    dataset = dataset.map(generate)
    if cardinality == tf.data.UNKNOWN_CARDINALITY:
      dataset = dataset.filter(lambda _: True)
    self.assertEqual(dataset.cardinality(), cardinality)

    dataset = batching_utils.dynamic_batch(
        dataset,
        SizeConstraints(
            total_num_components=4, total_num_nodes={}, total_num_edges={}))
    self.assertEqual(dataset.cardinality(), tf.data.UNKNOWN_CARDINALITY)
    result = list(dataset)
    self.assertLen(result, 3)
    self.assertAllEqual(result[0].num_components, [1, 0, 2])
    self.assertAllEqual(
        result[0].context.features['f'],
        as_ragged([[[.5, .5]], [], [[.5, .5], [.5, .5]]], ragged_rank=1))
    self.assertAllEqual(result[1].num_components, [3])
    self.assertAllEqual(
        result[1].context.features['f'],
        as_ragged([[[.5, .5], [.5, .5], [.5, .5]]], ragged_rank=1))
    self.assertAllEqual(result[2].num_components, [2])
    self.assertAllEqual(result[2].context.features['f'],
                        as_ragged([[[.5, .5], [.5, .5]]], ragged_rank=1))

  @parameterized.parameters([tf.data.UNKNOWN_CARDINALITY, 6])
  def testDynamicBatching2(self, cardinality):

    def generate(num_components):
      sizes = tf.ones([num_components], dtype=tf.int64)
      features = {'f': tf.fill([num_components, 2], value=.5)}
      return gt.GraphTensor.from_pieces(
          gt.Context.from_fields(features=features, sizes=sizes))

    dataset = tf.data.Dataset.from_tensor_slices([0, 1, 2, 3, 2, 2])
    dataset = dataset.map(generate)
    if cardinality == tf.data.UNKNOWN_CARDINALITY:
      dataset = dataset.filter(lambda _: True)
    self.assertEqual(dataset.cardinality(), cardinality)

    dataset = batching_utils.dynamic_batch(
        dataset,
        SizeConstraints(
            total_num_components=4, total_num_nodes={}, total_num_edges={}))
    self.assertEqual(dataset.cardinality(), tf.data.UNKNOWN_CARDINALITY)
    result = list(dataset)
    self.assertLen(result, 3)
    self.assertAllEqual(result[0].num_components, [0, 1, 2])
    self.assertAllEqual(
        result[0].context.features['f'],
        as_ragged([[], [[.5, .5]], [[.5, .5], [.5, .5]]], ragged_rank=1))
    self.assertAllEqual(result[1].num_components, [3])
    self.assertAllEqual(
        result[1].context.features['f'],
        as_ragged([[[.5, .5], [.5, .5], [.5, .5]]], ragged_rank=1))
    self.assertAllEqual(result[2].num_components, [2, 2])
    self.assertAllEqual(
        result[2].context.features['f'],
        as_ragged([[[.5, .5]] * 2, [[.5, .5]] * 2], ragged_rank=1))

  @parameterized.parameters(
      [tf.data.UNKNOWN_CARDINALITY, tf.data.INFINITE_CARDINALITY])
  def testInfiniteDataset(self, cardinality):

    def generate(num_components):
      sizes = tf.ones([num_components], dtype=tf.int64)
      return gt.GraphTensor.from_pieces(gt.Context.from_fields(sizes=sizes))

    dataset = tf.data.Dataset.from_tensor_slices([1, 2, 1])
    dataset = dataset.map(generate)
    dataset = dataset.repeat()
    if cardinality == tf.data.UNKNOWN_CARDINALITY:
      dataset = dataset.filter(lambda _: True)
    self.assertEqual(dataset.cardinality(), cardinality)

    dataset = batching_utils.dynamic_batch(
        dataset,
        SizeConstraints(
            total_num_components=3, total_num_nodes={}, total_num_edges={}))

    self.assertEqual(dataset.cardinality(), cardinality)
    dataset = dataset.map(lambda g: g.total_num_components)
    dataset = dataset.take(3 * 100)
    # (1 2) (1 1) (2 1) (1 2) (1 1) (2 1) ..
    self.assertEqual(list(dataset.as_numpy_iterator()), [3, 2, 3] * 100)

  test_a2b4_ab3_graph = gt.GraphTensor.from_pieces(
      node_sets={
          'a': gt.NodeSet.from_fields(features={'f': [1., 2.]}, sizes=[2]),
          'b': gt.NodeSet.from_fields(features={}, sizes=[4]),
      },
      edge_sets={
          'a->b':
              gt.EdgeSet.from_fields(
                  features={'f': as_tensor([1., 2., 3.])},
                  sizes=as_tensor([3]),
                  adjacency=adj.Adjacency.from_indices(
                      ('a', as_tensor([0, 1, 1])),
                      ('b', as_tensor([0, 1, 3])),
                  )),
      },
  )
  test_a1b1_ab1_graph = gt.GraphTensor.from_pieces(
      node_sets={
          'a': gt.NodeSet.from_fields(features={'f': [3.]}, sizes=[1]),
          'b': gt.NodeSet.from_fields(features={}, sizes=[1]),
      },
      edge_sets={
          'a->b':
              gt.EdgeSet.from_fields(
                  features={'f': as_tensor([4.])},
                  sizes=as_tensor([1]),
                  adjacency=adj.Adjacency.from_indices(
                      ('a', as_tensor([0])),
                      ('b', as_tensor([0])),
                  )),
      },
  )

  def testGraphBatching(self):

    def generate(index):
      return tf.cond(
          index <= 1,
          lambda: self.test_a1b1_ab1_graph,
          lambda: self.test_a2b4_ab3_graph,
      )

    dataset = tf.data.Dataset.range(5)
    dataset = dataset.map(generate)
    dataset = batching_utils.dynamic_batch(
        dataset,
        SizeConstraints(
            total_num_components=4,
            total_num_nodes={
                'a': 5,
                'b': 7
            },
            total_num_edges={'a->b': 6}))
    result = list(dataset)
    # [(1,1,1), (1,1,1), (2,4,3)], [(2,4,3)], [(2,4,3)]
    self.assertLen(result, 3)
    self.assertAllEqual(result[0].num_components, [1, 1, 1])
    self.assertAllEqual(result[0].node_sets['a'].sizes, [[1], [1], [2]])
    self.assertAllEqual(result[0].node_sets['a']['f'],
                        as_ragged([[3.], [3.], [1., 2.]]))
    self.assertAllEqual(result[0].node_sets['b'].sizes, [[1], [1], [4]])
    self.assertAllEqual(result[0].edge_sets['a->b'].sizes, [[1], [1], [3]])
    self.assertAllEqual(result[0].edge_sets['a->b']['f'],
                        as_ragged([[4.], [4.], [1., 2., 3.]]))

    def check_equal(x, y):
      self.assertAllEqual(x, y)
      return x

    self.assertAllEqual(result[1].num_components, [1])
    tf.nest.map_structure(
        check_equal,
        result[1].merge_batch_to_components(),
        self.test_a2b4_ab3_graph,
        expand_composites=True)

    self.assertAllEqual(result[2].num_components, [1])
    tf.nest.map_structure(
        check_equal,
        result[2].merge_batch_to_components(),
        self.test_a2b4_ab3_graph,
        expand_composites=True)

  def testRaisesOnInvalidConfig(self):

    dataset = tf.data.Dataset.from_tensors(self.test_a1b1_ab1_graph)

    def batch(dataset, constraints):
      return batching_utils.dynamic_batch(dataset, constraints)

    no_a_node = SizeConstraints(
        total_num_components=1,
        total_num_nodes={'b': 100},
        total_num_edges={'a->b': 100})
    self.assertRaisesRegex(
        ValueError,
        ('The maximum total number of <a> nodes must be specified as'
         r' `constraints.total_num_nodes\[<a>\]`'),
        lambda: batch(dataset, no_a_node))

    no_edge = SizeConstraints(
        total_num_components=1,
        total_num_nodes={
            'a': 100,
            'b': 100
        },
        total_num_edges={'?': 200})
    self.assertRaisesRegex(
        ValueError,
        ('The maximum total number of <a->b> edges must be specified as'
         r' `constraints.total_num_edges\[<a->b>\]`'),
        lambda: batch(dataset, no_edge))

  @parameterized.parameters([True, False])
  def testRaisesOnImpossibleBatching(self, repeat):

    def generate(index):
      return tf.cond(
          index <= 2,
          lambda: self.test_a1b1_ab1_graph,
          lambda: self.test_a2b4_ab3_graph,
      )

    dataset = tf.data.Dataset.range(5)
    dataset = dataset.map(generate)
    if repeat:
      dataset = dataset.repeat()

    def batch(dataset, constraints):
      dataset = batching_utils.dynamic_batch(dataset, constraints)
      dataset = dataset.take(5)
      return list(dataset)

    components_overflow = SizeConstraints(
        total_num_components=0,
        total_num_nodes={
            'a': 100,
            'b': 100
        },
        total_num_edges={'a->b': 100})
    self.assertRaisesRegex(
        tf.errors.InvalidArgumentError,
        ('Could not pad graph as it already has more graph components'
         ' then it is allowed by `total_sizes.total_num_components`'),
        lambda: batch(dataset, components_overflow))

    nodes_overflow = preprocessing.SizeConstraints(
        total_num_components=2,
        total_num_nodes={
            'a': 100,
            'b': 2
        },
        total_num_edges={'a->b': 100})
    self.assertRaisesRegex(tf.errors.InvalidArgumentError,
                           ('Could not pad <b> as it already has more nodes'
                            ' then it is allowed by the'
                            r' `total_sizes.total_num_nodes\[<b>\]`'),
                           lambda: batch(dataset, nodes_overflow))

    edges_overflow = SizeConstraints(
        total_num_components=2,
        total_num_nodes={
            'a': 100,
            'b': 100
        },
        total_num_edges={'a->b': 2})
    self.assertRaisesRegex(tf.errors.InvalidArgumentError,
                           ('Could not pad <a->b> as it already has more edges'
                            ' then it is allowed by the'
                            r' `total_sizes.total_num_edges\[<a->b>\]'),
                           lambda: batch(dataset, edges_overflow))


def _gt_from_sizes(sizes: SizeConstraints) -> gt.GraphTensor:
  context = gt.Context.from_fields(
      sizes=tf.ones([sizes.total_num_components], dtype=tf.int32))

  node_sets = {}
  for name, total_size in sizes.total_num_nodes.items():
    zeros = tf.zeros([sizes.total_num_components - 1], dtype=tf.int32)
    node_sets[name] = gt.NodeSet.from_fields(
        sizes=tf.concat([[total_size], zeros], axis=0),
        features={'_dummy_': tf.zeros([total_size, 0], tf.float32)})

  edge_sets = {}
  for name, total_size in sizes.total_num_edges.items():
    source, target = name.split('->')
    indices = tf.zeros(total_size, dtype=tf.int32)
    zeros = tf.zeros([sizes.total_num_components - 1], dtype=tf.int32)
    edge_sets[name] = gt.EdgeSet.from_fields(
        sizes=tf.concat([[total_size], zeros], axis=0),
        adjacency=adj.Adjacency.from_indices((source, indices),
                                             (target, indices)))

  return gt.GraphTensor.from_pieces(
      context=context, node_sets=node_sets, edge_sets=edge_sets)


class ConstraintsTestBase(tu.GraphTensorTestBase):

  def assertContraintsEqual(self, actual, expected):
    tf.nest.map_structure(
        functools.partial(
            self.assertAllEqual, msg=f'actual={actual}, expected={expected}'),
        actual, expected)


class MinimumSizeConstraintsTest(ConstraintsTestBase):

  def testEmptyDataset(self):
    ds = tf.data.Dataset.from_tensors(
        _gt_from_sizes(SizeConstraints(5, {'n': 3}, {'n->n': 6})))
    ds = ds.take(0)
    result = batching_utils.find_tight_size_constraints(ds)
    self.assertContraintsEqual(
        result,
        SizeConstraints(tf.int64.min, {'n': tf.int64.min},
                        {'n->n': tf.int64.min}))

  @parameterized.parameters([(SizeConstraints(1, {}, {}),),
                             (SizeConstraints(32, {}, {}),),
                             (SizeConstraints(5, {'n': 3}, {}),),
                             (SizeConstraints(5, {'n': 3}, {'n->n': 6}),),
                             (SizeConstraints(1, {
                                 'a': 2,
                                 'b': 3
                             }, {'a->b': 4}),)])
  def testSingleExample(self, value: SizeConstraints):
    ds = tf.data.Dataset.from_tensors(_gt_from_sizes(value))
    result = batching_utils.find_tight_size_constraints(ds)
    self.assertContraintsEqual(result, value)

  def testMultipleExamples(self):

    def generator(size):
      return _gt_from_sizes(
          SizeConstraints(size, {
              'a': size + 1,
              'b': size + 2
          }, {'a->b': size + 3}))

    ds = tf.data.Dataset.range(1, 101).map(generator)
    ds = ds.shuffle(100, seed=42)
    result = batching_utils.find_tight_size_constraints(ds)
    self.assertContraintsEqual(
        result,
        SizeConstraints(100 + 1, {
            'a': 101 + 1,
            'b': 102 + 1
        }, {'a->b': 103}))

  def testRaisesOnInfiniteInput(self):
    ds = tf.data.Dataset.from_tensors(
        _gt_from_sizes(SizeConstraints(5, {'n': 3}, {'n->n': 6})))
    ds = ds.repeat()
    self.assertRaisesRegex(
        ValueError, 'The dataset must be finite',
        lambda: batching_utils.find_tight_size_constraints(ds))

  def testRaisesOnNotGraphTensorElements(self):
    ds = tf.data.Dataset.range(0, 10)
    self.assertRaisesRegex(
        ValueError, 'The element of dataset must be GraphTensor',
        lambda: batching_utils.find_tight_size_constraints(ds))


class ConstraintsForStaticBatchTest(ConstraintsTestBase):

  def assertContraintsEqual(self, actual, expected):
    tf.nest.map_structure(
        functools.partial(
            self.assertAllEqual, msg=f'actual={actual}, expected={expected}'),
        actual, expected)

  @parameterized.product(batch_size=[1, 2, 3, 5, 10], num_components=[1, 5])
  def testStaticShapeContext(self, batch_size: int, num_components: int):
    ds = tf.data.Dataset.from_tensors(
        _gt_from_sizes(SizeConstraints(num_components, {}, {})))
    actual = batching_utils.learn_fit_or_skip_size_constraints(
        ds, batch_size=batch_size, sample_size=100)

    self.assertContraintsEqual(
        actual,
        SizeConstraints(
            total_num_components=batch_size * num_components,
            total_num_nodes={},
            total_num_edges={}))

  def testBulkParameters(self):
    ds = tf.data.Dataset.from_tensors(
        _gt_from_sizes(SizeConstraints(1, {}, {})))
    batch_sampled_sizes = [1, 2]
    actual = batching_utils.learn_fit_or_skip_size_constraints(
        ds,
        batch_size=batch_sampled_sizes,
        success_ratio=[0.5, 0.6, 0.7],
        sample_size=10)
    self.assertLen(actual, 2)
    for actual_b, batch_size in zip(actual, batch_sampled_sizes):
      self.assertLen(actual_b, 3)
      for actual_br in actual_b:
        self.assertEqual(actual_br.total_num_components, batch_size)

  @parameterized.product(batch_size=[1, 2, 10], success_ratio=[.5, .9, 1.])
  def testStaticShapeGraph(self, batch_size: int, success_ratio: float):
    ds = tf.data.Dataset.from_tensors(
        _gt_from_sizes(SizeConstraints(1, {
            'a': 2,
            'b': 3
        }, {'a->b': 4})))

    actual = batching_utils.learn_fit_or_skip_size_constraints(
        ds, batch_size=batch_size, success_ratio=success_ratio, sample_size=100)

    self.assertContraintsEqual(
        actual,
        SizeConstraints(
            total_num_components=1 * batch_size,
            total_num_nodes={
                'a': 2 * batch_size,
                'b': 3 * batch_size
            },
            total_num_edges={'a->b': 4 * batch_size}))

  @parameterized.product(batch_size=[1, 2], var_num_edges=[True, False])
  def testMaxPadding(self, batch_size: int, var_num_edges: bool):
    assert batch_size < 5, (
        'Larger batch sizes may require larger `sample_size` as the chances'
        ' of getting the largest possible graph exponentially go to zero.')
    sample_size = 1_000
    max_ab_edges = 4
    max_a_nodes = 2
    max_b_nodes = 3

    def generator(index) -> gt.GraphTensor:
      num_edges = index % (1 + max_ab_edges) if var_num_edges else max_ab_edges
      return _gt_from_sizes(
          SizeConstraints(
              1, {
                  'a': (1 + (index * 17 + 53) % max_a_nodes),
                  'b': (1 + (index * 53 + 19) % max_b_nodes),
              }, {'a->b': num_edges}))

    ds = tf.data.Dataset.range(sample_size).shuffle(sample_size)
    ds = ds.map(generator)

    actual = batching_utils.learn_fit_or_skip_size_constraints(
        ds, batch_size=batch_size, sample_size=sample_size, success_ratio=1.)

    self.assertContraintsEqual(
        actual,
        SizeConstraints(
            total_num_components=1 * batch_size + 1,
            total_num_nodes={
                'a': max_a_nodes * batch_size + (1 if var_num_edges else 0),
                'b': max_b_nodes * batch_size + (1 if var_num_edges else 0)
            },
            total_num_edges={'a->b': max_ab_edges * batch_size}))

  @parameterized.parameters([100, 400])
  def testOnNormalLimit(self, batch_size: int):
    sample_size = 10_000

    def generator(index) -> gt.GraphTensor:
      return _gt_from_sizes(
          SizeConstraints(1, {
              'node': 2,
          }, {'node->node': index % 2}))

    avg = std = 0.5

    ds = tf.data.Dataset.range(sample_size).shuffle(sample_size)
    ds = ds.map(generator)

    actual = batching_utils.learn_fit_or_skip_size_constraints(
        ds,
        batch_size=batch_size,
        sample_size=sample_size,
        success_ratio=[0.5000, 0.6914, 0.8413, 0.9332, 0.9772])

    self.assertLen(actual, 5)
    for constraints, n_std in zip(actual, [0.0, 0.5, 1.0, 1.5, 2.0]):
      self.assertIsInstance(constraints, SizeConstraints)
      self.assertEqual(constraints.total_num_components, batch_size * 1 + 1)
      self.assertEqual(constraints.total_num_nodes['node'], 2 * batch_size + 1)
      num_edges = avg * batch_size + n_std * std * math.sqrt(batch_size)
      self.assertAllClose(
          float(constraints.total_num_edges['node->node']),
          num_edges,
          atol=1.0,
          msg=f'n_std={n_std}')

  @parameterized.parameters([1, 5, 10])
  def testAgainstBruteForceSolution(self, batch_size: int):
    # Exactly solves the problem of static batch processing for particular
    # homogeneous graph type using the grid search and compares the obtained
    # result with the `learn_fit_or_skip_size_constraints`.
    sample_size = 10_000
    success_ratio = 0.9

    num_nodes_12 = tf.random.uniform([sample_size], 1, 3, dtype=tf.int32)
    num_edges_04 = 4 * tf.random.uniform([sample_size], 0, 2, dtype=tf.int32)

    def generator(num_nodes, num_edges) -> gt.GraphTensor:
      return _gt_from_sizes(
          SizeConstraints(1, {
              'node': num_nodes,
          }, {'node->node': num_edges}))

    ds = tf.data.Dataset.zip(
        (tf.data.Dataset.from_tensor_slices(num_nodes_12),
         tf.data.Dataset.from_tensor_slices(num_edges_04))).map(generator)

    actual = batching_utils.learn_fit_or_skip_size_constraints(
        ds,
        batch_size=batch_size,
        sample_size=sample_size,
        success_ratio=success_ratio)

    # Below we solve optimal batching problem using the grid search.
    def get_reachable_constraints():
      n = tf.range(batch_size, 2 * batch_size + 1)
      e = 4 * tf.range(0, batch_size + 1)
      result = tf.stack(tf.meshgrid(n, e, indexing='ij'), axis=-1)
      return tf.reshape(result, (-1, 2))

    # Create matrix with all possible combinations of node and edge sizes.
    reachable_constraints = get_reachable_constraints()
    # Create random sample of node/edge total sizes using Binomial Distribution.
    sampled_sizes = tf.stack(
        values=[
            batch_size + tf.random.stateless_binomial([sample_size],
                                                      seed=[7, batch_size],
                                                      counts=batch_size,
                                                      probs=0.5),
            4 * tf.random.stateless_binomial([sample_size],
                                             seed=[19, batch_size],
                                             counts=batch_size,
                                             probs=0.5),
        ],
        axis=-1)
    # Estimate the fraction of samples that satisfies `reachable_constraints`.
    sample_fits = tf.reduce_all(
        tf.expand_dims(reachable_constraints, 1) >= sampled_sizes, axis=-1)
    success_ratios = tf.reduce_mean(tf.cast(sample_fits, tf.float32), axis=1)

    # Filter all constraints that have success ratio above the `success_ratio`.
    allowed_sampled_sizes = tf.boolean_mask(
        reachable_constraints, success_ratios >= success_ratio, axis=0)
    # Find the constraint with the smallest total budget (#nodes + #edges).
    opt_sampled_sizes = allowed_sampled_sizes[tf.argmin(
        tf.reduce_sum(allowed_sampled_sizes, axis=-1))]

    # Extract expected number of nodes and edges taking into account padding.
    expected_num_nodes = opt_sampled_sizes[0] + 1
    expected_num_edges = opt_sampled_sizes[1]
    self.assertGreater(expected_num_nodes, int(1.5 * batch_size))
    self.assertGreater(expected_num_edges, int(2.0 * batch_size))
    self.assertEqual(actual.total_num_nodes['node'], expected_num_nodes)
    self.assertEqual(actual.total_num_edges['node->node'], expected_num_edges)


if __name__ == '__main__':
  tf.test.main()