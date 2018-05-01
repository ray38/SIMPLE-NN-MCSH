import tensorflow as tf
import numpy as np
import random
import six
from six.moves import cPickle as pickle
import collections
from ..utils import *

"""
Neural network model with symmetry function as a descriptor
"""

"""
def pickle_load(filename):
    with open(filename, 'rb') as fil:
        if six.PY2:
            return pickle.load(fil)
        elif six.PY3:
            return pickle.load(fil, encoding='latin1')
"""

# TODO: complete the code
# TODO: add the part for selecting the memory device(CPU or GPU)
# TODO: validation set & test set
class Neural_network(object):
    def __init__(self):
        self.parent = None
        self.key = 'neural_network'
        self.default_inputs = {'neural_network':
                                  {
                                      'method': 'Adam',
                                      'continue': False,
                                      'use_force': False,
                                      'force_coeff': 0.3,
                                      'total_epoch': 10000,
                                      'save_interval': 1000,
                                      'show_interval': 100,
                                      'max_iteration': 1000,
                                      'batch_size': 64,
                                      'loss_scale': 1.,
                                      'double_precision': True,
                                      'use_atomic_weight': False,
                                      'scale': False,
                                      'data': ['./train_dir'],
                                      'learning_rate': 0.01,
                                      'optimizer': dict(),
                                      'nodes': '30-30',
                                      'atomic_weights': {
                                          'type': None
                                          'params': dict()
                                      }
                                  }
                              }
        self.inputs = dict()
        self.global_step = tf.Variable(0, trainable=False)

    def _make_fileiter(self):
        # TODO: check tf.data
        """
        data_list = list()
        for item in self.inputs['data']:
            with open(item, 'r') as fil:
                for line in fil:
                    data_list.append(line.strip())
        """
        data_list = _make_data_list(self.inputs['data'])
        data_list = list(zip(data_list, list(range(len(data_list)))))
 
        class iterfile(object):
            def __init__(self, filelist):
                self.items = filelist
                self.index = 0

            def __iter__(self):
                return self
            
            def _next(self):
                if self.index == 0:
                    random.shuffle(self.items)
        
                n = self.items[self.index]
                self.index += 1
                self.index = self.index % len(self.items)
                return n

            if six.PY2:
                def next(self):
                    return self._next()
            elif six.PY3:
                def __next__(self):
                    return self._next()

        self.filelist = iterfile(data_list)

    def _get_batch(self, batch_size, initial=False):
        self.batch = {
                        'x': dict(),
                        'dx': dict(),
                        '_E': list(),
                        '_F': list(),
                        'N': dict(),
                        'seg_id': dict()
                      }
        
        tag_atomic_weights = self.inputs['atomic_weights']['type']
        if tag_atomic_weights != None:
            self.batch['atomic_weights'] = list()

        for item in self.parent.inputs['atom_types']:
            self.batch['x'][item] = list()
            self.batch['dx'][item] = list()
            self.batch['N'][item] = list()
        
        for i,item in enumerate(self.filelist):
            loaded_fil = pickle_load(item[0])

            # TODO: add parameter check part
            self.batch['_E'].append(loaded_fil['E'])
            self.batch['_F'].append(loaded_fil['F'])
            for jtem in self.parent.inputs['atom_types']:
                self.batch['x'][jtem].append(loaded_fil['x'][jtem])
                self.batch['dx'][jtem].append(loaded_fil['dx'][jtem])
                self.batch['N'][jtem].append(loaded_fil['N'][jtem])
                if tag_atomic_weights != None:
                    self.batch['atomic_weights'].
                        append(self.atomic_weights_full[self.atomic_weights_full[item][:,1] == item[1],:])

            if i+2 > batch_size:
                break

        self.batch['_E'] = np.array(self.batch['_E'], dtype=np.float64)
        self.batch['_F'] = np.concatenate(self.batch['_F']).astype(np.float64)
        if tag_atomic_weights != None:
            self.batch['atomic_weights'] = np.concatenate(self.batch['atomic_weights']).astype(np.float64)

        self.batch['tot_num'] = np.sum(list(self.batch['N'].values()), axis=0)
        max_atom_num = np.max(self.batch['tot_num'])
        #total_atom_num = np.sum(atom_num_per_structure)

        if initial:
            self.inp_size = dict()

        for item in self.parent.inputs['atom_types']:
            self.batch['N'][item] = np.array(self.batch['N'][item], dtype=np.int)
            self.batch['x'][item] = np.concatenate(self.batch['x'][item], axis=0).astype(np.float64)
            self.batch['x'][item] -= self.scale[item][0:1,:]
            self.batch['x'][item] /= self.scale[item][1:2,:]

            if initial:
                self.inp_size[item] = self.batch['x'][item].shape[1]
            else:
                if self.inp_size[item] != self.batch['x'][item].shape[1]:
                    raise ValueError

            tmp_dx = np.zeros([np.sum(self.batch['N'][item]), self.inp_size[item],\
                               max_atom_num, 3], dtype=np.float64)

            tmp_idx = 0
            for jtem in self.batch['dx'][item]:
                tmp_dx[tmp_idx:tmp_idx+jtem.shape[0],:,\
                       :jtem.shape[2],:] = jtem
                tmp_idx += jtem.shape[0]
            self.batch['dx'][item] = tmp_dx / self.scale[item][1:2,:].reshape([1,self.inp_size[item],1,1])

            self.batch['seg_id'][item] = \
                np.concatenate([[j]*jtem for j,jtem in enumerate(self.batch['N'][item])])

        self.batch['partition'] = \
            np.concatenate([[0]*item + [1]*(max_atom_num - item) for item in self.batch['tot_num']])
        # TODO: gdf?

    def _set_scale_parameter(self, scale_file, gdf_file=None):
        self.scale = pickle_load(scale_file)
        # TODO: add the check code for valid scale file
        self.gdf = pickle_load(gdf_file)

    def _make_model(self):
        self.models = dict()
        self.ys = dict()
        self.dys = dict()

        if self.inputs['double_precision']:
            dtype = tf.float64
        else:
            dtype = tf.float32

        dense_basic_setting = {
            'dtype': dtype,
            'kernel_initializer': tf.initializers.truncated_normal(stddev=0.3),
            'bias_initializer': tf.initializers.truncated_normal(stddev=0.3)
        }

        for item in self.parent.inputs['atom_types']:
            if isinstance(self.inputs['nodes'], collections.Mapping):
                nodes = list(map(int, self.inputs['nodes'][item].split('-')))
            else:
                nodes = list(map(int, self.inputs['nodes'].split('-')))
            nlayers = len(nodes)
            model = tf.keras.models.Sequential()
            model.add(tf.keras.layers.Dense(nodes[0], activation='sigmoid', \
                                            input_dim=self.inp_size[item],
                                            **dense_basic_setting))

            for i in range(1, nlayers):
                model.add(tf.keras.layers.Dense(nodes[i], activation='sigmoid', **dense_basic_setting))
            model.add(tf.keras.layers.Dense(1, activation='linear', **dense_basic_setting))

            self.models[item] = model
            self.ys[item] = self.models[item](self.x[item])

            if self.inputs['use_force']:
                self.dys[item] = tf.gradients(self.ys[item], self.x[item])[0]
            else:
                self.dys[item] = None


    def _calc_output(self):
        self.E = self.F = 0

        for item in self.parent.inputs['atom_types']:
            self.E += tf.segment_sum(self.ys[item], self.seg_id[item])

            if self.inputs['use_force']:
                tmp_force = self.dx[item] * \
                            tf.expand_dims(\
                                tf.expand_dims(self.dys[item], axis=2),
                                axis=3)
                tmp_force = tf.reduce_sum(\
                                tf.segment_sum(tmp_force, self.seg_id[item]),
                                axis=1)
                self.F -= tf.dynamic_partition(tf.reshape(tmp_force, [-1,3]),
                                                   self.partition, 2)[0]

    def _get_loss(self, use_gdf=False, atomic_weights=None):
        self.e_loss = tf.reduce_mean(tf.square((self._E - self.E) / self.tot_num))
        self.total_loss = self.e_loss

        if self.inputs['use_force']:
            self.f_loss = tf.square(self._F - self.F)
            if use_gdf:
                self.f_loss *= gdf_values
            self.f_loss = tf.reduce_mean(self.f_loss) * self.inputs['force_coeff']
        
            self.total_loss += self.f_loss

    def _make_optimizer(self, user_optimizer=None):
        final_loss = self.inputs['loss_scale']*self.total_loss
        if self.inputs['method'] == 'L-BFGS-B':
            self.optim = tf.contrib.opt.ScipyOptimizerInterface(final_loss, 
                                                                method=self.inputs['method'], 
                                                                options=self.inputs['optimizer'])
        elif self.inputs['method'] == 'Adam':
            if isinstance(self.inputs['learning_rate'], collections.Mapping):
                self.learning_rate = tf.train.exponential_decay(global_step=self.global_step, **self.inputs['learning_rate'])
            else:
                self.learning_rate = self.inputs['learning_rate']

            self.optim = tf.train.AdamOptimizer(learning_rate=self.learning_rate, 
                                                name='Adam', **self.inputs['optimizer'])
            self.optim = self.optim.minimize(final_loss, global_step=self.global_step)
        else:
            if user_optimizer != None:
                self.optim = user_optimizer.minimize(final_loss, global_step=self.global_step)
            else:
                raise ValueError

    def _make_feed_dict(self):
        self.fdict = {
            self._E: self.batch['_E'],
            self._F: self.batch['_F'],
            self.tot_num: self.batch['tot_num'],
            self.partition: self.batch['partition']
        }

        if self.inputs['atomic_weights']['type'] != None:
            self.fdict[self.atomic_weights]: self.batch['atomic_weights']

        for item in self.parent.inputs['atom_types']:
            self.fdict[self.x[item]] = self.batch['x'][item]
            self.fdict[self.dx[item]] = self.batch['dx'][item]
            self.fdict[self.seg_id[item]] = self.batch['seg_id'][item] 

    def _generate_lammps_potential(self):
        # TODO: get the parameter info from initial batch generting processs
        return 0

    def _save(self, sess, saver):
        self.parent.logfile.write("Save the weights and write the LAMMPS potential..")              
        saver.save(sess, './SAVER')
        self._generate_lammps_potential()

    def train(self, user_optimizer=None, user_atomic_weights_function=None):
        # FIXME: make individual function to set self.inputs?
        self.inputs = self.parent.inputs['neural_network']
        # read data?
        # preprocessing: scale, GDF...

        self._make_fileiter()

        if self.inputs['atomic_weights']['type'] == 'gdf':
            get_atomic_weights = _generate_gdf_file
        elif self.inputs['atomic_weights']['type'] == 'user':
            get_atomic_weights = user_atomic_weights_function
        elif self.inputs['atomic_weights']['type'] == 'file':
            get_atomic_weights = './atomic_weights'
        else:
            get_atomic_weights = None

        self.scale, self.atomic_weights_full = \
            preprocessing(self.inputs['data'], self.parent.inputs['atom_types'], 'x', \
                          calc_scale=self.inputs['scale'], \
                          get_atomic_weights=get_atomic_weights, \
                          **self.inputs['atomic_weights']['params'])

        self._get_batch(1, initial=True)

        # Generate placeholder
        self._E = tf.placeholder(tf.float64, [None])
        self._F = tf.placeholder(tf.float64, [None, 3])
        self.tot_num = tf.placeholder(tf.float64, [None])
        self.partition = tf.placeholder(tf.int32, [None])
        self.seg_id = dict()
        self.x = dict()
        self.dx = dict()
        self.atomic_weights = tf.placeholder(tf.float64, [None, 1]) \
                                if self.inputs['atomic_weights']['type'] != None else None
        for item in self.parent.inputs['atom_types']:
            self.x[item] = tf.placeholder(tf.float64, [None, self.inp_size[item]])
            self.dx[item] = tf.placeholder(tf.float64, [None, self.inp_size[item], None, 3])
            self.seg_id[item] = tf.placeholder(tf.int32, [None])

        self._make_model()
        self._calc_output()
        self._get_loss()
        self._make_optimizer(user_optimizer=user_optimizer)

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        #config.gpu_options.per_process_gpu_memory_fraction = 0.45
        with tf.Session(config=config) as sess:
            # Load or initialize the variables
            saver = tf.train.Saver()
            if self.inputs['continue']:
                saver.restore(sess, './SAVER')
            else:
                sess.run(tf.global_variables_initializer())

            if self.inputs['method'] == 'L-BFGS-B':
                # TODO: complete this part
                raise ValueError
            elif self.inputs['method'] == 'Adam':
                for epoch in range(self.inputs['total_epoch']):
                    self._get_batch(self.inputs['batch_size'])
                    self._make_feed_dict()
                    self.optim.run(feed_dict=self.fdict)

                    # Logging
                    if (epoch+1) % self.inputs['show_interval'] == 0:
                        result = "epoch {}: ".format(epoch)

                        eloss = sess.run(self.e_loss, feed_dict=self.fdict)
                        eloss = np.sqrt(eloss)
                        result += 'E loss = {}'.format(eloss)

                        if self.inputs['use_force']:
                            floss = sess.run(self.f_loss, feed_dict=self.fdict)
                            floss = np.sqrt(floss*3/self.inputs['force_coeff'])
                            result += ', F loss = {}'.format(floss)

                        lr = sess.run(self.learning_rate)
                        result += ', learning_rate: {}\n'.format(lr)
                        self.parent.logfile.write(result)

                    # Temp saving
                    if (epoch+1) % self.inputs['save_interval'] == 0:
                        self._save(sess, saver)

            self._save(sess, saver)
    