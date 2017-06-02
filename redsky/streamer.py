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
        input_info: list of tuple
            dictionary describing the incoming streams
        output_info: dict
            dictionary describing the resulting stream
        provenance : dict, optional
            metadata about this operation

        Notes
        ------
        input_info is designed to map keys in streams to kwargs in functions.
        It is critical for the internal data from the events to be returned,
        upon `event_guts`.
        input_info = [('input_kwarg', 'data_key')]
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
        self.provenence = None

    def generate_provanance(self, func=None, **kwargs):
        d = dict(module=inspect.getmodule(func),
                 # this line gets more complex with the integration class
                 function_name=func.__name__, )
        return d

    def dispatch(self, nds):
        """Dispatch to methods expecting particular doc types."""
        # If we get multiple streams
        if isinstance(nds[0], tuple):
            names, docs = list(zip(*nds))
            if len(set(names)) > 1:
                raise RuntimeError('Misaligned Streams')
            name = names[0]
        else:
            names, docs = nds
            name = names
            docs = (docs,)
        # if event expose raw event data
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
                                  **self.output_info)
        # We are not actually going to change the data, maybe just filter it
        # no truly new data needed
        elif len(docs) == 1:
            new_descriptor = dict(uid=self.outbound_descriptor_uid,
                                  time=time.time(),
                                  run_start=self.run_start_uid,
                                  data_keys=docs[0]['data_keys']
                                  )
        # I don't know how to filter multiple streams so fail
        else:
            raise RuntimeError("You can either put a new output against "
                               "multiple streams, or you are filtering a "
                               "single stream, pick one")
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
        # If handed a single doc
        if isinstance(docs, dict):
            docs = (docs, )
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
        if len(self.output_info['returns']) == 1:
            outputs = (outputs,)
        new_event = dict(uid=str(uuid.uuid4()),
                         time=time.time(),
                         timestamps={},
                         descriptor=self.outbound_descriptor_uid,
                         # use the return positions list to properly map the
                         # output data to the data keys
                         data={output_name: output
                               for output_name, output in
                               zip(self.output_info['returns'], outputs)},
                         seq_num=self.i)
        self.i += 1
        return 'event', new_event

    # If we need to issue a new doc then just pass it through
    def event(self, docs):
        if len(docs) == 1:
            return docs[0]
        else:
            raise RuntimeError("I can't pass through multiple event docs")

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
