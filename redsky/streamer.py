"""Module for automatically storing processed data in a databroker"""
##############################################################################
#
# redsky            by Billinge Group
#                   Simon J. L. Billinge sb2896@columbia.edu
#                   (c) 2016 trustees of Columbia University in the City of
#                        New York.
#                   All rights reserved
#
# File coded by:    Christopher J. Wright
#
# See AUTHORS.txt for a list of people who contributed.
# See LICENSE.txt for license information.
#
##############################################################################
from copy import deepcopy as dc

import time
from metadatastore.core import doc_or_uid_to_uid
import inspect
import uuid
import subprocess


def db_store_single_resource_single_file(db, fs_data_name_save_map=None):
    """Decorator for adding data to a databroker. This requires all the savers
    to create one resource/datum per file.

    Parameters
    ----------
    db: databroker.Broker instance
        The databroker to store the data in
    fs_data_name_save_map: dict
        The dictionary which maps data names to (Saver, saver_args,
        {saver_kwargs})

    Yields
    -------
    name, doc:
        The name of the document and the document itself
    """
    if fs_data_name_save_map is None:
        fs_data_name_save_map = {}  # {'name': (SaverClass, args, kwargs)}

    def wrap(f):
        def wrapped_f(*args, **kwargs):
            gen = f(*args, **kwargs)
            for name, doc in gen:
                fs_doc = dc(doc)

                if name == 'descriptor':
                    # Mutate the doc here to handle filestore
                    for data_name in fs_data_name_save_map.keys():
                        fs_doc['data_keys'][data_name].update(
                            external='FILESTORE:')

                elif name == 'event':
                    # Mutate the doc here to handle filestore
                    for data_name, save_tuple in fs_data_name_save_map.items():
                        # Create instance of Saver
                        s = save_tuple[0](db.fs, *save_tuple[1],
                                          **save_tuple[2])
                        fs_uid = s.write(fs_doc['data'][data_name])
                        fs_doc['data'][data_name] = fs_uid
                        s.close()

                    doc.update(
                        filled={k: True for k in fs_data_name_save_map.keys()})

                # Always stash the (potentially) filestore mutated doc
                db.mds.insert(name, fs_doc)

                # Always yield the pristine doc
                yield name, doc

        return wrapped_f

    return wrap


class Doc(object):
    def __init__(self, output_info=None, input_info=None):
        """
        Serve up documents and their internals as requested.
        The main way that this works is by a) ingesting documents, b) issuing
        documents, c) returning the internals of documents upon request.

        Parameters
        ----------
        input_info: list of tuples
            describs the incoming streams
        output_info: list of tuples
            describs the resulting stream
        provenance : dict, optional
            metadata about this operation

        Notes
        ------
        input_info is designed to map keys in streams to kwargs in functions.
        It is critical for the internal data from the events to be returned,
        upon `event_guts`.
        input_info = [('input_kwarg', 'data_key')]

        output_info is designed to take the output tuple and map it back into
        data_keys.
        output_info = [('data_key', {'dtype': 'array', 'source': 'testing'})]
        """
        if output_info is None:
            output_info = {}
        if input_info is None:
            input_info = {}
        self.run_start_uid = None
        self.input_info = input_info
        self.output_info = output_info
        self.i = 0
        self.outbound_descriptor_uid = None
        self.provenence = {}

    def generate_provenance(self, stream_class, func):
        d = dict(function_module=inspect.getmodule(func),
                 # this line gets more complex with the integration class
                 function_name=func.__name__,
                 stream_class=stream_class.__name__,
                 stream_class_module=inspect.getmodule(stream_class),
                 conda_list=subprocess.check_output(['conda', 'list',
                                                     '-e']).decode(),
                 output_info=self.output_info,
                 input_info=self.input_info
                 )
        return d

    def curate_streams(self, nds):
        # If we get multiple streams make (doc, doc, doc, ...)
        if isinstance(nds[0], tuple):
            names, docs = list(zip(*nds))
            if len(set(names)) > 1:
                raise RuntimeError('Misaligned Streams')
            name = names[0]
        # If only one stream then (doc, )
        else:
            names, docs = nds
            name = names
            docs = (docs,)
        return name, docs

    def dispatch(self, nds):
        """
        Dispatch to methods expecting particular doc types.

        Notes
        ------
        This takes in a tuple ((name, document), (name, document)).
        This then re-packages this as (document, document) and dispatches
        to the corresponding method.
        """
        name, docs = self.curate_streams(nds)
        return getattr(self, name)(docs)

    def start(self, docs):
        """
        Issue new start document for input documents

        Parameters
        ----------
        docs: tuple of dicts or dict

        Returns
        -------

        """
        self.run_start_uid = str(uuid.uuid4())
        new_start_doc = dict(uid=self.run_start_uid,
                             time=time.time(),
                             parents=[doc['uid'] for doc in docs],
                             # parent_keys=[k for k in stream_keys],
                             provenance=self.provenence)
        return 'start', new_start_doc

    def descriptor(self, docs):
        if self.run_start_uid is None:
            raise RuntimeError("Received EventDescriptor before "
                               "RunStart.")
        # If we had to describe the output information then we need an all new
        # descriptor
        self.outbound_descriptor_uid = str(uuid.uuid4())
        if self.output_info:
            inbound_descriptor_uids = [doc_or_uid_to_uid(doc) for doc in docs]
            # TODO: add back data_keys
            new_descriptor = dict(uid=self.outbound_descriptor_uid,
                                  time=time.time(),
                                  run_start=self.run_start_uid,
                                  data_keys={k:v for k, v in self.output_info})
        # We are not actually going to change the data, maybe just filter it
        # no truly new data needed or we are combining copies of the same
        # descriptor
        elif (len(docs) == 1
              or all(d['data_keys'] == docs[0]['data_keys'] for d in docs)):
            new_descriptor = dict(uid=self.outbound_descriptor_uid,
                                  time=time.time(),
                                  run_start=self.run_start_uid,
                                  data_keys=docs[0]['data_keys']
                                  )
        # I don't know how to filter multiple streams so fail
        else:
            raise RuntimeError("Descriptor mismatch: "
                               "you have tried to combine descriptors with "
                               "different data keys")
        return 'descriptor', new_descriptor

    def event_guts(self, docs):
        """
        Provide some of the event data as a dict, which may be used as kwargs

        Parameters
        ----------
        docs

        Returns
        -------

        """
        return {input_kwarg: doc['data'][data_key] for
                (input_kwarg, data_key), doc in zip(self.input_info, docs)}

    def issue_event(self, outputs):
        if self.run_start_uid is None:
            raise RuntimeError("Received Event before RunStart.")
        # TODO: figure out a way to halt the stream if we issue an error stop
        if isinstance(outputs, Exception):
            new_stop = dict(uid=str(uuid.uuid4()),
                            time=time.time(),
                            run_start=self.run_start_uid,
                            reason=repr(outputs),
                            exit_status='failure')
            return 'stop', new_stop

        # Make a new event with no data
        if len(self.output_info) == 1:
            outputs = (outputs,)
        new_event = dict(uid=str(uuid.uuid4()),
                         time=time.time(),
                         timestamps={},
                         descriptor=self.outbound_descriptor_uid,
                         # use the return positions list to properly map the
                         # output data to the data keys
                         data={output_name: output
                               for output_name, output in
                               zip(self.output_info[0], outputs)},
                         seq_num=self.i)
        self.i += 1
        return 'event', new_event

    # If we need to issue a new doc then just pass it through
    # XXX: this is dangerous, note that we are not issuing a name doc pair
    # but multiple docs without names
    def event(self, docs):
        return docs

    def stop(self, docs):
        if self.run_start_uid is None:
            raise RuntimeError("Received RunStop before RunStart.")
        new_stop = dict(uid=str(uuid.uuid4()),
                        time=time.time(),
                        run_start=self.run_start_uid,
                        exit_status='success')
        self.outbound_descriptor_uid = None
        self.run_start_uid = None
        return 'stop', new_stop


class StoreSink(object):
    """Sink of documents to save them to the databases.

    The input stream of (name, document) pairs passes through unchanged.
    As a side effect, documents are inserted into the databases and external
    files may be written.

    Parameters
    ----------
    db: ``databroker.Broker`` instance
        The databroker to store the documents in, must have writeable
        metadatastore and writeable filestore if ``external`` is not empty.
    external_writers : dict
        Maps data keys to a ``WriterClass``, which is responsible for writing
        data to disk and creating a record in filestore. It will be
        instantiated (possible multiple times) with the argument ``db.fs``.
        If it requires additional arguments, use ``functools.partial`` to
        produce a callable that requires only ``db.fs`` to instantiate the
        ``WriterClass``.
        """
    def __init__(self, db, external_writers=None):
        self.db = db
        if external_writers is None:
            self.external_writers = {}  # {'name': WriterClass}
        else:
            self.external_writers = external_writers
        self.writers = None

    def __call__(self, nd_pair):
        name, doc = nd_pair
        name, doc, fs_doc = getattr(self, name)(doc)
        # The mutated fs_doc is inserted into metadatastore.
        fs_doc.pop('filled', None)
        fs_doc.pop('_name', None)
        self.db.mds.insert(name, fs_doc)

        # The pristine doc is yielded.
        return name, doc

    def event(self, doc):
        fs_doc = dict(doc)
        # We need a selectively deeper copy since we will mutate
        # fs_doc['data'].
        fs_doc['data'] = dict(fs_doc['data'])
        # The writer writes data to an external file, creates a
        # datum record in the filestore database, and return that
        # datum_id. We modify fs_doc in place, replacing the data
        # values with that datum_id.
        for data_key, writer in self.writers.items():
            # data doesn't have to exist
            if data_key in fs_doc['data']:
                fs_uid = writer.write(fs_doc['data'][data_key])
                fs_doc['data'][data_key] = fs_uid

        doc.update(
            filled={k: False for k in self.external_writers.keys()})
        return 'event', doc, fs_doc

    def descriptor(self, doc):
        fs_doc = dict(doc)
        # Mutate fs_doc here to mark data as external.
        for data_name in self.external_writers.keys():
            # data doesn't have to exist
            if data_name in fs_doc['data_keys']:
                fs_doc['data_keys'][data_name].update(
                    external='FILESTORE:')
        return 'descriptor', doc, fs_doc
        
    def start(self, doc):
        # Make a fresh instance of any WriterClass classes.
        self.writers = {data_key: cl(self.db.fs)
                   for data_key, cl in self.external_writers.items()}
        return 'start', doc, doc
    
    def stop(self, doc):
        for data_key, writer in list(self.writers.items()):
            writer.close()
            self.writers.pop(data_key)
        return 'stop', doc, doc
