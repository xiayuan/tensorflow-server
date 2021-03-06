#Inspired by https://github.com/aymericdamien/TensorFlow-Examples/blob/master/examples/3%20-%20Neural%20Networks/recurrent_network.py
import tensorflow as tf
from tensorflow.contrib import rnn

import numpy as np
import pickle

import text

import os

import math
import sys
import tempfile
import time


flags = tf.app.flags
flags.DEFINE_string("data_dir", "/tmp/mnist-data",
                    "Directory for storing mnist data")
flags.DEFINE_boolean("download_only", False,
                     "Only perform downloading of data; Do not proceed to "
                     "session preparation, model definition or training")
flags.DEFINE_integer("task_index", None,
                     "Worker task index, should be >= 0. task_index=0 is "
                     "the master worker task the performs the variable "
                     "initialization ")
flags.DEFINE_integer("num_gpus", 2,
                     "Total number of gpus for each machine."
                     "If you don't use GPU, please set it to '0'")
flags.DEFINE_integer("replicas_to_aggregate", None,
                     "Number of replicas to aggregate before parameter update"
                     "is applied (For sync_replicas mode only; default: "
                     "num_workers)")
flags.DEFINE_integer("hidden_units", 100,
                     "Number of units in the hidden layer of the NN")
flags.DEFINE_integer("train_steps", 10000,
                     "Number of (global) training steps to perform")
flags.DEFINE_integer("batch_size", 100, "Training batch size")
flags.DEFINE_float("learning_rate", 0.01, "Learning rate")
flags.DEFINE_boolean("sync_replicas", False,
                     "Use the sync_replicas (synchronized replicas) mode, "
                     "wherein the parameter updates from workers are aggregated "
                     "before applied to avoid stale gradients")
flags.DEFINE_boolean(
    "existing_servers", False, "Whether servers already exists. If True, "
    "will use the worker hosts via their GRPC URLs (one client process "
    "per worker host). Otherwise, will create an in-process TensorFlow "
    "server.")
flags.DEFINE_string("ps_hosts","yq01-hpc-bdlgpu07.yq01.baidu.com:2222",
                    "Comma-separated list of hostname:port pairs")
flags.DEFINE_string("worker_hosts", "yq01-hpc-bdlgpu07.yq01.baidu.com:2223,yq01-hpc-bdlgpu15.yq01.baidu.com:2223",
                    "Comma-separated list of hostname:port pairs")
flags.DEFINE_string("job_name", None,"job name: worker or ps")

FLAGS = flags.FLAGS


batch_size = 32
test_size = 256


################################################################################
# lstm training data
################################################################################

vocab_size = 21000
embedding_size = 256
time_step_size = 40
lstm_size = 256


inputs = file('tf_trainval_sq.pkl', 'rb')
tf_trainval_sq = pickle.load(inputs)
trX_lstm = tf_trainval_sq.astype('int32') + 1

inputs = file('tf_test_sq.pkl', 'rb')
tf_test_sq = pickle.load(inputs)
teX_lstm = tf_test_sq.astype('int32') + 1


################################################################################
# tfidf training data
################################################################################

corpus = []
corpus_train = []
corpus_test = []

max_features = vocab_size = 21000

with open('kaoshi_data_sample_ex2b','r') as f:
    ff = f.readlines()
    for i in ff:
        corpus.append(i.strip())

tok = text.Tokenizer(max_features)
tok.fit_on_texts(corpus)
f.close()

with open('kaoshi_train_data_sample_ex2b_rectify','r') as f:
    ff = f.readlines()
    for i in ff:
        corpus_train.append(i.strip())

corpus_train_matrix = tok.texts_to_matrix(corpus_train, mode='tfidf')
f.close()

with open('kaoshi_test_data_sample_ex2b_rectify','r') as f:
    ff = f.readlines()
    for i in ff:
        corpus_test.append(i.strip())

corpus_test_matrix = tok.texts_to_matrix(corpus_test, mode='tfidf')
f.close()

trX_tfidf = corpus_train_matrix
teX_tfidf = corpus_test_matrix


################################################################################
# label
################################################################################
inputs = file('tf_trainval_label.pkl', 'rb')
tf_trainval_label = pickle.load(inputs)
trY = tf_trainval_label

inputs = file('tf_test_sq_label.pkl', 'rb')
tf_test_sq_label = pickle.load(inputs)
teY = tf_test_sq_label






def init_weights(shape):
    return tf.Variable(tf.random_normal(shape, stddev=0.01))


def model(X_lstm, X_tfidf, W_tfidf, lstm_size, W, p_keep_hidden=0.9,):     
    # lstm 
    # input_seq vocab_size = 21000, embedding_size = 256
    embedding_maxtrix = tf.get_variable("embedding", [vocab_size, embedding_size], dtype=tf.float32)
    word_embeddings = tf.nn.embedding_lookup(embedding_maxtrix, X_lstm)   # batchsize * 40 * 256
    XT = tf.transpose(word_embeddings, [1, 0, 2])  # 40 * batchsize * 256
    XR = tf.reshape(XT, [-1, lstm_size])  # each row has input for each lstm cell (lstm_size=256)
    X_split = tf.split(XR, time_step_size, 0) # split them to time_step_size (40 arrays)
    # Each array shape: (batch_size, input_vec_size=256)

    # Make lstm with lstm_size (each input vector size)
    lstm = rnn.BasicLSTMCell(lstm_size, forget_bias=1.0, state_is_tuple=True)

    # Get lstm cell output, time_step_size (40) arrays with lstm_size output: (batch_size, lstm_size)
    outputs, _states = rnn.static_rnn(lstm, X_split, dtype=tf.float32)

    # dnn
    h = tf.nn.relu(tf.matmul(X_tfidf, W_tfidf))
    h = tf.nn.dropout(h, p_keep_hidden)

    # merge 
    merge_vec = tf.concat([outputs[-1], h], 1)

    return tf.matmul(merge_vec, W)


def main(unused_argv):

    if FLAGS.job_name is None or FLAGS.job_name == "":
        raise ValueError("Must specify an explicit `job_name`")
    if FLAGS.task_index is None or FLAGS.task_index =="":
        raise ValueError("Must specify an explicit `task_index`")

    print("job name = %s" % FLAGS.job_name)
    print("task index = %d" % FLAGS.task_index)

    #Construct the cluster and start the server
    ps_spec = FLAGS.ps_hosts.split(",")
    worker_spec = FLAGS.worker_hosts.split(",")
    # Get the number of workers.
    num_workers = len(worker_spec)

    cluster = tf.train.ClusterSpec({
            "ps": ps_spec,
            "worker": worker_spec})

    if not FLAGS.existing_servers:
        # Not using existing servers. Create an in-process server.
        server = tf.train.Server(
                cluster, job_name=FLAGS.job_name, task_index=FLAGS.task_index)
        if FLAGS.job_name == "ps":
            server.join()

    is_chief = (FLAGS.task_index == 0)
    if FLAGS.num_gpus > 0:
        if FLAGS.num_gpus < num_workers:
            raise ValueError("number of gpus is less than number of workers")
        # Avoid gpu allocation conflict: now allocate task_num -> #gpu 
        # for each worker in the corresponding machine
        gpu = (FLAGS.task_index % FLAGS.num_gpus)
        worker_device = "/job:worker/task:%d/gpu:%d" % (FLAGS.task_index, gpu)
    elif FLAGS.num_gpus == 0:
        # Just allocate the CPU to worker server
        cpu = 0
        worker_device = "/job:worker/task:%d/cpu:%d" % (FLAGS.task_index, cpu)


################################################################################################
## ADD NEW CODE HERE
################################################################################################

    # The device setter will automatically place Variables ops on separate
    # parameter servers (ps). The non-Variable ops will be placed on the workers.
    # The ps use CPU and workers use corresponding GPU
    
    with tf.device(
          tf.train.replica_device_setter(
              worker_device=worker_device,
              ps_device="/job:ps/cpu:0",
              cluster=cluster)):

        global_step = tf.Variable(0, name="global_step", trainable=False)

        X_lstm = tf.placeholder(tf.int32, [None, 40])
        X_tfidf = tf.placeholder("float", [None, vocab_size])
        Y = tf.placeholder(tf.int32, [None, 230])

        W_tfidf = init_weights([vocab_size, 40])
        W = init_weights([lstm_size + 40 , 230])

        py_x = model(X_lstm, X_tfidf, W_tfidf, lstm_size, W)

        cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=py_x, labels=Y))
        train_op = tf.train.AdamOptimizer(0.001).minimize(cost, global_step=global_step)
        predict_op = tf.argmax(py_x, 1)

################################################################################################
## ADD NEW CODE HERE
################################################################################################


        # you need to initialize all variables
        init_op = tf.global_variables_initializer()
        # train_dir = tempfile.mkdtemp()
        train_dir = './ckpt'

        saver = tf.train.Saver()

        sv = tf.train.Supervisor(
              is_chief=is_chief,
              logdir=train_dir,
              init_op=init_op,
              recovery_wait_secs=1,
              global_step=global_step)

        sess_config = tf.ConfigProto(
            allow_soft_placement=True,
            log_device_placement=False,
            device_filters=["/job:ps", "/job:worker/task:%d" % FLAGS.task_index])

        if is_chief:
            print("Worker %d: Initializing session..." % FLAGS.task_index)
        else:
            print("Worker %d: Waiting for session to be initialized..." %
                        FLAGS.task_index)

        if FLAGS.existing_servers:
            server_grpc_url = "grpc://" + worker_spec[FLAGS.task_index]
            print("Using existing server at: %s" % server_grpc_url)

            sess = sv.prepare_or_wait_for_session(server_grpc_url, config=sess_config)
        else:
            sess = sv.prepare_or_wait_for_session(server.target, config=sess_config)

        print("Worker %d: Session initialization complete." % FLAGS.task_index)

        # Perform training
        time_begin = time.time()
        print("Training begins @ %f" % time_begin)

        local_step = 0

        while True:
            for start, end in zip(range(0, len(trX_lstm), batch_size), range(batch_size, len(trX_lstm)+1, batch_size)):
                _, step = sess.run([train_op, global_step], feed_dict={X_lstm: trX_lstm[start:end], X_tfidf: trX_tfidf[start:end], Y: trY[start:end]})
                local_step += 1
                now = time.time()
                # print("%f: Worker %d: training step %d done (global step: %d)" % (now, FLAGS.task_index, local_step, step))


            test_indices = np.arange(len(teX_lstm))  # Get A Test Batch
            np.random.shuffle(test_indices)
            test_indices = test_indices[0:test_size]
            print("top 1 accuracy: ")
            print(local_step, np.mean(np.argmax(teY[test_indices], axis=1) ==
                             sess.run(predict_op, feed_dict={X_lstm: teX_lstm[test_indices], X_tfidf: teX_tfidf[test_indices]})))

################################################################################################
## THIS UGLY CODE IS FOR SOLVING PROBLEM OF IN_TOP_K
## solve the problem: Graph is finalized and cannot be modified
## tf.train.Supervisor will finalized the graph, so we need to rebuild a new graph, 
## and copy the original graph using tf.train.import_meta_graph("xxx.meta", clear_devices=True)
################################################################################################

            # g = tf.Graph()
            # with tf.Session(graph=g) as sess2:
            #     ckpt = tf.train.get_checkpoint_state(train_dir)
            #     new_saver = tf.train.import_meta_graph(ckpt.model_checkpoint_path + u'.meta', clear_devices=True)
            #     if ckpt and ckpt.model_checkpoint_path:
            #         new_saver.restore(sess2, ckpt.model_checkpoint_path)

            #     print("top 5 accuracy: ")
            #     labels = np.argmax(teY[test_indices], axis=1)
            #     logits = sess.run(py_x, feed_dict={X_lstm: teX_lstm[test_indices], X_tfidf: teX_tfidf[test_indices]})

            #     correct = tf.nn.in_top_k(logits, labels, 5)
            #     # total_correct = tf.reduce_sum(tf.cast(correct, tf.int32))
            #     accuracy = tf.reduce_mean(tf.cast(correct, tf.float32))
            #     print(local_step, accuracy.eval(session=sess2))

################################################################################################
## THIS UGLY CODE IS FOR SOLVING PROBLEM OF IN_TOP_K
################################################################################################

            if step >= FLAGS.train_steps:
                break

            time_end = time.time()
            print("Training ends @ %f" % time_end)
            training_time = time_end - time_begin
            print("Training elapsed time: %f s" % training_time)

if __name__ == "__main__":
    tf.app.run()
