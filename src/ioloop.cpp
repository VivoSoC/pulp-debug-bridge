/*
 * Copyright (C) 2018 ETH Zurich and University of Bologna
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/* 
 * Authors: Germain Haugou, ETH (germain.haugou@iis.ee.ethz.ch)
 */

#include "loops.hpp"

#include <stdio.h>

LooperFinishedStatus Ioloop::register_proc(hal_debug_struct_t *debug_struct) {
  try {
    unsigned int value = 0;
    m_top->access(true, PTR_2_INT(&debug_struct->use_internal_printf), 4, (char*)&value);
    return LooperFinishedContinue;
  } catch (LoopCableException e) {
    log.error("IO loop cable error: exiting\n");
    return LooperFinishedStopAll;
  }
}

uint32_t Ioloop::print_len(hal_debug_struct_t *debug_struct) {
#ifdef __NEW_REQLOOP__
  if (!m_top->get_target_available()) return 0;
#endif
  uint32_t value;
  m_top->access(false, PTR_2_INT(&debug_struct->pending_putchar), 4, (char*)&value);
  return value;
}

void Ioloop::print_one(hal_debug_struct_t *debug_struct, uint32_t len) {
  char buff[len+1];
  m_top->access(false, PTR_2_INT(&debug_struct->putc_buffer), len, &(buff[0]));
  buff[len] = 0;
  unsigned int zero = 0;
  m_top->access(true, PTR_2_INT(&debug_struct->pending_putchar), 4, (char*)&zero);
  fputs(buff, stdout);
  fflush(NULL);
}

void Ioloop::print_loop(hal_debug_struct_t *debug_struct) {
  m_event_loop->getTimerEvent([this, debug_struct](){
    // printf("ioloop fast loop proc\n");
    try {
      uint32_t len = print_len(debug_struct);
      if (len == 0) {
        set_paused(false);
        return kEventLoopTimerDone;
      }
      print_one(debug_struct, len);
      return m_printing_pause;
    } catch (LoopCableException e) {
      return kEventLoopTimerDone;
    }
    return kEventLoopTimerDone;
  }, 0);
}

LooperFinishedStatus Ioloop::loop_proc(hal_debug_struct_t *debug_struct)
{
  // printf("ioloop proc\n");
  try {
    uint32_t len = print_len(debug_struct);
    if (len == 0) return LooperFinishedContinue;
    print_one(debug_struct, len);
    // check again to see if we launch the timer
    if (print_len(debug_struct) > 0) {
      print_loop(debug_struct);
      return LooperFinishedPause;
    } else {
      return LooperFinishedContinue;
    }
  } catch (LoopCableException e) {
    return LooperFinishedStopAll;
  }
}

Ioloop::Ioloop(LoopManager * top, const EventLoop::SpEventLoop &event_loop, int64_t printing_pause) : 
  Looper(top), log("IOLOOP"), m_event_loop(std::move(event_loop)), m_printing_pause(printing_pause)
{
}
